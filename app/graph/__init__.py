"""
TraceGraph AI — Neo4j Graph Builder

Responsibilities:
1. Create schema (constraints + indexes)
2. Load all node types (Requirement, Page, UIElement, CodeFile, CodeSymbol, UserFlow, PullRequest, PRChange)
3. Create cross-layer edges (COVERS, IMPLEMENTED_BY, PART_OF, STEP_IN, REQUIRES, ABSENT, TOUCHES, MODIFIES)
4. Run cross-layer linker (Req→UI via embeddings, UI→Code via name matching)
5. Run absence detection pass

All Cypher queries use parameterized inputs — no string interpolation.
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from app.llm import LLMProvider, cosine_similarity, get_llm_provider
from app.models import (
    BlastRadiusReport,
    CodeFile,
    CodeSymbol,
    CoverageStatus,
    Evidence,
    EvidenceType,
    Page,
    PRChange,
    PullRequest,
    Requirement,
    Transition,
    UIElement,
    UserFlow,
)

logger = logging.getLogger(__name__)


class GraphUnavailableError(RuntimeError):
    """Raised when Neo4j is unavailable; impact reports must not be fabricated."""


class GraphBuilder:
    """
    Builds and queries the Neo4j knowledge graph.
    Uses parameterized Cypher — no string interpolation on user data.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        # The Neo4j driver is imported lazily to keep API startup fail-closed
        # when the optional database runtime is unavailable.
        self._driver: Any = None
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._driver.verify_connectivity()
            logger.info("GraphBuilder connected to Neo4j at %s", uri)
        except Exception as e:
            logger.warning("Could not initialize Neo4j driver at %s: %s", uri, e)
            self._driver = None

    @property
    def available(self) -> bool:
        return self._driver is not None

    def _require_driver(self) -> None:
        if not self._driver:
            raise GraphUnavailableError("Neo4j is unavailable. Start the configured database before building or querying a graph.")

    def close(self) -> None:
        if self._driver:
            self._driver.close()

    @staticmethod
    def _ui_code_mapping_score(element: UIElement, symbol: CodeSymbol) -> tuple[float, str]:
        """Return a conservative, explainable UI-to-code mapping score."""
        label_normalized = re.sub(r"[^a-z0-9]", "", element.label.lower())
        label_words = {word for word in re.findall(r"[a-z0-9]+", element.label.lower()) if len(word) > 2}
        label_terms = set(label_words)
        if len(label_normalized) > 2:
            label_terms.add(label_normalized)
        symbol_normalized = re.sub(r"[^a-z0-9]", "", symbol.name.lower())
        if not label_terms or not symbol_normalized:
            return 0.0, "name_match"

        name_overlap = sum(1 for word in label_words if word in symbol_normalized)
        score = name_overlap / max(len(label_words), 1)
        if len(label_normalized) >= 3 and (
            label_normalized in symbol_normalized or symbol_normalized in label_normalized
        ):
            score = max(score, 0.8)
        if score:
            return score, "name_match"

        path_words = set(re.findall(r"[a-z0-9]+", symbol.file_path.lower()))
        path_words -= {"app", "component", "components", "core", "feature", "features", "page", "pages", "src", "ts"}
        if "auth" in path_words:
            path_words.update({"login", "signin", "signup", "register", "authentication"})
        if label_terms & path_words:
            return 0.55, "file_path_semantic_match"
        return 0.0, "name_match"

    @staticmethod
    def _requirement_ui_coverage_score(requirement: Requirement, element: UIElement) -> float:
        """Compute bounded semantic coverage without broad category leakage."""
        category_keywords: dict[str, set[str]] = {
            "product": {"product", "listing", "detail", "description", "image", "cart"},
            "product_attributes": {"attribute", "dropdown", "swatch", "color", "size", "combobox", "search"},
            "cart": {"cart", "basket", "quantity", "remove"},
            "checkout": {"checkout", "address", "shipping", "payment", "order"},
            "content": {"page", "content", "cms"},
            "general": set(),
        }
        requirement_terms = set(re.findall(r"[a-z0-9]+", requirement.text.lower()))
        requirement_terms |= category_keywords.get(requirement.category, set())
        auth_terms = {"authentication", "authenticate", "login", "logout", "register", "signin", "signup"}
        if requirement_terms & auth_terms:
            requirement_terms |= auth_terms

        label_normalized = re.sub(r"[^a-z0-9]", "", element.label.lower())
        element_terms = {word for word in re.findall(r"[a-z0-9]+", element.label.lower()) if len(word) > 2}
        if len(label_normalized) > 2:
            element_terms.add(label_normalized)
        if not element_terms:
            return 0.0

        overlap = len(requirement_terms & element_terms) / max(len(requirement_terms), 1)
        if requirement_terms & auth_terms and element_terms & auth_terms:
            overlap = max(overlap, 0.3)
        return overlap

    # ─────────────────────────────────────────
    #  Schema Setup
    # ─────────────────────────────────────────

    def create_schema(self) -> None:
        """Create constraints and indexes. Idempotent."""
        self._require_driver()
        constraints = [
            "CREATE CONSTRAINT req_id IF NOT EXISTS FOR (n:Requirement) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT page_id IF NOT EXISTS FOR (n:Page) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT ui_id IF NOT EXISTS FOR (n:UIElement) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT flow_id IF NOT EXISTS FOR (n:UserFlow) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT codesym_fqn IF NOT EXISTS FOR (n:CodeSymbol) REQUIRE n.fqn IS UNIQUE",
            "CREATE CONSTRAINT codefile_path IF NOT EXISTS FOR (n:CodeFile) REQUIRE n.path IS UNIQUE",
            "CREATE CONSTRAINT pr_num IF NOT EXISTS FOR (n:PullRequest) REQUIRE n.number IS UNIQUE",
            "CREATE CONSTRAINT prchange_id IF NOT EXISTS FOR (n:PRChange) REQUIRE n.id IS UNIQUE",
        ]
        with self._driver.session() as session:
            for c in constraints:
                try:
                    session.run(c)
                except Exception as e:
                    logger.debug("Constraint already exists: %s", e)
        logger.info("Graph schema created")

    def clear_active_evidence_graph(self) -> None:
        """Replace the active, dedicated TraceGraph index before a rebuild.

        Raw crawl/code/requirement artifacts are immutable files; Neo4j is the
        query index for exactly one selected evidence run.  Clearing owned
        labels prevents identical page IDs from separate crawls from creating
        mixed-run report paths.
        """
        self._require_driver()
        cypher = """
        MATCH (n)
        WHERE n:Requirement OR n:Page OR n:UIElement OR n:UserFlow
           OR n:CodeFile OR n:CodeSymbol OR n:PullRequest OR n:PRChange
        DETACH DELETE n
        """
        with self._driver.session() as session:
            session.run(cypher)

    # ─────────────────────────────────────────
    #  Node Loaders
    # ─────────────────────────────────────────

    def load_requirements(self, requirements: list[Requirement]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (r:Requirement {id: item.id})
        SET r.text = item.text,
            r.category = item.category,
            r.source_url = item.source_url,
            r.source_text = item.source_text,
            r.testability_score = item.testability_score,
            r.coverage_status = item.coverage_status
        """
        items = [r.model_dump(mode="json") for r in requirements]
        with self._driver.session() as session:
            session.run(cypher, items=items)
        logger.info("Loaded %d Requirement nodes", len(requirements))

    def load_flows(self, flows: list[UserFlow]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (f:UserFlow {id: item.id})
        SET f.name = item.name,
            f.description = item.description
        """
        with self._driver.session() as session:
            session.run(cypher, items=[f.model_dump(mode="json") for f in flows])
        logger.info("Loaded %d UserFlow nodes", len(flows))

    def load_pages(self, pages: list[Page]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (p:Page {id: item.id})
        SET p.url = item.url,
            p.title = item.title,
            p.flow_id = item.flow_id,
            p.step_order = item.step_order
        """
        with self._driver.session() as session:
            session.run(cypher, items=[p.model_dump(mode="json") for p in pages])
        logger.info("Loaded %d Page nodes", len(pages))

    def load_ui_elements(self, elements: list[UIElement]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (e:UIElement {id: item.id})
        SET e.page_id = item.page_id,
            e.selector = item.selector,
            e.label = item.label,
            e.element_type = item.element_type,
            e.data_test_id = item.data_test_id
        """
        with self._driver.session() as session:
            session.run(cypher, items=[e.model_dump(mode="json") for e in elements])
        logger.info("Loaded %d UIElement nodes", len(elements))

    def load_code_files(self, files: list[CodeFile]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (f:CodeFile {path: item.path})
        SET f.language = item.language,
            f.component_name = item.component_name
        """
        with self._driver.session() as session:
            session.run(cypher, items=[f.model_dump(mode="json") for f in files])
        logger.info("Loaded %d CodeFile nodes", len(files))

    def load_code_symbols(self, symbols: list[CodeSymbol]) -> None:
        cypher = """
        UNWIND $items AS item
        MERGE (s:CodeSymbol {fqn: item.fqn})
        SET s.name = item.name,
            s.symbol_type = item.symbol_type,
            s.file_path = item.file_path,
            s.start_line = item.start_line,
            s.end_line = item.end_line,
            s.is_component = item.is_component,
            s.is_hook = item.is_hook,
            s.exported = item.exported
        """
        with self._driver.session() as session:
            session.run(cypher, items=[s.model_dump(mode="json") for s in symbols])
        logger.info("Loaded %d CodeSymbol nodes", len(symbols))

    def load_pull_request(self, pr: PullRequest, changes: list[PRChange]) -> None:
        pr_cypher = """
        MERGE (p:PullRequest {number: $number})
        SET p.title = $title, p.author = $author, p.html_url = $html_url,
            p.base_branch = $base_branch, p.head_sha = $head_sha
        """
        change_cypher = """
        UNWIND $items AS item
        MERGE (c:PRChange {id: item.id})
        SET c.file_path = item.file_path,
            c.change_type = item.change_type,
            c.additions = item.additions,
            c.deletions = item.deletions,
            c.changed_symbols = item.changed_symbols,
            c.symbol_mapping_method = item.symbol_mapping_method
        WITH c, item
        MATCH (pr:PullRequest {number: item.pr_number})
        MERGE (c)-[:PART_OF_PR]->(pr)
        WITH c, item
        MATCH (f:CodeFile {path: item.file_path})
        MERGE (c)-[:TOUCHES]->(f)
        """
        with self._driver.session() as session:
            session.run(pr_cypher, **pr.model_dump(mode="json"))
            session.run(change_cypher, items=[c.model_dump(mode="json") for c in changes])
        logger.info("Loaded PullRequest #%d with %d changes", pr.number, len(changes))

    # ─────────────────────────────────────────
    #  Edge Creators
    # ─────────────────────────────────────────

    def create_page_flow_edges(self, pages: list[Page], flows: list[UserFlow]) -> None:
        """STEP_IN: Page → UserFlow"""
        cypher = """
        UNWIND $items AS item
        MATCH (p:Page {id: item.page_id}), (f:UserFlow {id: item.flow_id})
        MERGE (p)-[r:STEP_IN]->(f)
        SET r.step_order = item.step_order
        """
        items = [
            {"page_id": p.id, "flow_id": p.flow_id, "step_order": p.step_order}
            for p in pages
            if p.flow_id
        ]
        with self._driver.session() as session:
            session.run(cypher, items=items)
        logger.info("Created %d STEP_IN edges", len(items))

    def create_element_page_edges(self, elements: list[UIElement]) -> None:
        """PART_OF: UIElement → Page"""
        cypher = """
        UNWIND $items AS item
        MATCH (e:UIElement {id: item.element_id}), (p:Page {id: item.page_id})
        MERGE (e)-[:PART_OF]->(p)
        """
        items = [{"element_id": e.id, "page_id": e.page_id} for e in elements]
        with self._driver.session() as session:
            session.run(cypher, items=items)
        logger.info("Created %d PART_OF edges", len(items))

    def create_flow_requirement_edges(self, flows: list[UserFlow]) -> None:
        """REQUIRES: UserFlow → Requirement"""
        cypher = """
        UNWIND $items AS item
        MATCH (f:UserFlow {id: item.flow_id}), (r:Requirement {id: item.req_id})
        MERGE (f)-[:REQUIRES]->(r)
        """
        items = [
            {"flow_id": flow.id, "req_id": req_id}
            for flow in flows
            for req_id in flow.requirement_ids
        ]
        with self._driver.session() as session:
            session.run(cypher, items=items)
        logger.info("Created %d REQUIRES edges", len(items))

    def create_symbol_file_edges(self, symbols: list[CodeSymbol]) -> None:
        """DEFINED_IN: CodeSymbol → CodeFile"""
        cypher = """
        UNWIND $items AS item
        MATCH (s:CodeSymbol {fqn: item.fqn}), (f:CodeFile {path: item.file_path})
        MERGE (s)-[r:DEFINED_IN]->(f)
        SET r.start_line = item.start_line, r.end_line = item.end_line
        """
        with self._driver.session() as session:
            session.run(
                cypher,
                items=[
                    {
                        "fqn": s.fqn,
                        "file_path": s.file_path,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                    }
                    for s in symbols
                ],
            )
        logger.info("Created %d DEFINED_IN edges", len(symbols))

    def create_pr_symbol_edges(self, changes: list[PRChange]) -> None:
        """MODIFIES: PRChange → CodeSymbol (based on symbol names detected in diff)"""
        cypher = """
        UNWIND $items AS item
        MATCH (c:PRChange {id: item.change_id})
        MATCH (s:CodeSymbol) WHERE s.name = item.symbol_name AND s.file_path = item.file_path
        MERGE (c)-[r:MODIFIES]->(s)
        SET r.delta_type = item.delta_type,
            r.mapping_method = item.mapping_method
        """
        items = []
        for change in changes:
            for sym_name in change.changed_symbols:
                items.append(
                    {
                        "change_id": change.id,
                        "symbol_name": sym_name,
                        "file_path": change.file_path,
                        "delta_type": change.change_type.value,
                        "mapping_method": change.symbol_mapping_method,
                    }
                )
        if items:
            with self._driver.session() as session:
                session.run(cypher, items=items)
            logger.info("Created %d MODIFIES edges (PR → Symbol)", len(items))

    # ─────────────────────────────────────────
    #  Cross-layer Linker
    # ─────────────────────────────────────────

    def create_ui_code_edges_by_name(
        self, elements: list[UIElement], symbols: list[CodeSymbol]
    ) -> None:
        """
        IMPLEMENTED_BY: UIElement → CodeSymbol
        Method: name-based matching (component name ↔ element label)
        Deterministic heuristic — no LLM.
        """
        edges_created = 0
        cypher = """
        MATCH (e:UIElement {id: $element_id}), (s:CodeSymbol {fqn: $symbol_fqn})
        MERGE (e)-[r:IMPLEMENTED_BY]->(s)
        SET r.confidence = $confidence,
            r.method = $method,
            r.evidence_type = $evidence_type
        """
        with self._driver.session() as session:
            for element in elements:
                best_sym: CodeSymbol | None = None
                best_score = 0.0
                best_method = "name_match"

                for sym in symbols:
                    score, method = self._ui_code_mapping_score(element, sym)

                    if score > best_score:
                        best_score = score
                        best_sym = sym
                        best_method = method

                if best_sym and best_score >= 0.4:
                    session.run(
                        cypher,
                        element_id=element.id,
                        symbol_fqn=best_sym.fqn,
                        confidence=round(best_score, 3),
                        method=best_method,
                        evidence_type=EvidenceType.NAME_MATCH.value,
                    )
                    edges_created += 1

        logger.info("Created %d IMPLEMENTED_BY edges (name matching)", edges_created)

    def create_requirement_ui_edges(
        self, requirements: list[Requirement], elements: list[UIElement]
    ) -> None:
        """
        COVERS: Requirement → UIElement
        Method: keyword overlap + category matching
        Deterministic — no LLM (embeddings used in linker.py if LLM available).
        """
        cypher = """
        MATCH (r:Requirement {id: $req_id}), (e:UIElement {id: $element_id})
        MERGE (r)-[rel:COVERS]->(e)
        SET rel.confidence = $confidence,
            rel.evidence_type = $evidence_type,
            rel.matcher = $matcher
        """

        edges_created = 0
        with self._driver.session() as session:
            for req in requirements:
                for elem in elements:
                    overlap = self._requirement_ui_coverage_score(req, elem)

                    if overlap >= 0.1:
                        confidence = min(overlap * 2.0, 0.95)
                        session.run(
                            cypher,
                            req_id=req.id,
                            element_id=elem.id,
                            confidence=round(confidence, 3),
                            evidence_type=EvidenceType.SEMANTIC_MATCH.value,
                            matcher="keyword_overlap",
                        )
                        edges_created += 1

        logger.info("Created %d COVERS edges (req→UI)", edges_created)

    def run_absence_detection(self, requirements: list[Requirement]) -> None:
        """
        Mark requirements that have no COVERS edge as UNVERIFIED.

        A bounded crawl cannot prove product-wide absence, so this method uses
        an explicit coverage-status property rather than creating an ABSENT
        relationship that would imply a false graph fact.
        """
        check_cypher = """
        MATCH (r:Requirement {id: $req_id})
        OPTIONAL MATCH (r)-[:COVERS]->(e:UIElement)
        RETURN count(e) AS covered_count
        """
        update_cypher = """
        MATCH (r:Requirement {id: $req_id})
        SET r.coverage_status = $status
        """
        with self._driver.session() as session:
            for req in requirements:
                result = session.run(check_cypher, req_id=req.id)
                record = result.single()
                if record is None:
                    raise GraphUnavailableError(
                        f"Coverage query returned no result for requirement '{req.id}'."
                    )
                count = int(record["covered_count"])

                if count == 0:
                    # A bounded crawl never proves product-wide absence. Keep the
                    # epistemic distinction explicit until an exhaustive coverage
                    # certificate has been recorded.
                    session.run(update_cypher, req_id=req.id, status=CoverageStatus.UNVERIFIED.value)
                elif count < 2:
                    session.run(update_cypher, req_id=req.id, status=CoverageStatus.PARTIAL.value)
                else:
                    session.run(update_cypher, req_id=req.id, status=CoverageStatus.COVERED.value)

        logger.info("Absence detection complete")

    # ─────────────────────────────────────────
    #  Query Interface
    # ─────────────────────────────────────────

    def get_node_counts(self) -> dict[str, int]:
        """Return counts for all node types."""
        self._require_driver()
        cypher = """
        CALL {
            MATCH (n:Requirement) RETURN 'Requirement' AS label, count(n) AS cnt
            UNION ALL MATCH (n:Page) RETURN 'Page' AS label, count(n) AS cnt
            UNION ALL MATCH (n:UIElement) RETURN 'UIElement' AS label, count(n) AS cnt
            UNION ALL MATCH (n:UserFlow) RETURN 'UserFlow' AS label, count(n) AS cnt
            UNION ALL MATCH (n:CodeFile) RETURN 'CodeFile' AS label, count(n) AS cnt
            UNION ALL MATCH (n:CodeSymbol) RETURN 'CodeSymbol' AS label, count(n) AS cnt
            UNION ALL MATCH (n:PullRequest) RETURN 'PullRequest' AS label, count(n) AS cnt
            UNION ALL MATCH (n:PRChange) RETURN 'PRChange' AS label, count(n) AS cnt
        }
        RETURN label, cnt ORDER BY label
        """
        with self._driver.session() as session:
            result = session.run(cypher)
            return {row["label"]: row["cnt"] for row in result}

    def query_blast_radius(
        self,
        pr_number: int,
        repo: str | None = None,
        changes: list[PRChange] | None = None,
        code_symbols: list[CodeSymbol] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Deterministic graph traversal: PR → Changed Files → Symbols → UI → Pages → Flows → Requirements.
        Executes the provenance traversal in Neo4j. Missing graph evidence yields no paths.
        """
        if self._driver:
            try:
                cypher = """
                MATCH (pr:PullRequest {number: $pr_number})<-[:PART_OF_PR]-(change:PRChange)
                OPTIONAL MATCH (change)-[:TOUCHES]->(file:CodeFile)
                OPTIONAL MATCH (change)-[modifies:MODIFIES]->(sym:CodeSymbol)
                OPTIONAL MATCH (ui:UIElement)-[implementation:IMPLEMENTED_BY]->(sym)
                OPTIONAL MATCH (ui)-[:PART_OF]->(page:Page)
                OPTIONAL MATCH (page)-[:STEP_IN]->(flow:UserFlow)
                OPTIONAL MATCH (req:Requirement)-[:COVERS]->(ui)
                RETURN
                    change.file_path AS file_path,
                    pr.number AS pr_number,
                    change.change_type AS change_type,
                    change.changed_symbols AS changed_symbols,
                    modifies.mapping_method AS code_mapping_method,
                    sym.name AS symbol_name,
                    sym.fqn AS symbol_fqn,
                    sym.is_component AS is_component,
                    ui.id AS ui_element_id,
                    ui.label AS ui_element_label,
                    implementation.method AS ui_mapping_method,
                    page.id AS page_id,
                    page.title AS page_title,
                    page.url AS page_url,
                    flow.id AS flow_id,
                    flow.name AS flow_name,
                    req.id AS req_id,
                    req.text AS req_text,
                    req.category AS req_category,
                    req.testability_score AS req_testability,
                    req.coverage_status AS req_coverage_status
                ORDER BY req.id, flow.id, ui.id
                """
                with self._driver.session() as session:
                    result = session.run(cypher, pr_number=pr_number)
                    rows = [dict(row) for row in result]
                    if rows and any(r.get("req_id") for r in rows):
                        return rows
            except Exception as e:
                logger.warning("Neo4j blast radius query failed (%s) — using dynamic graph traversal", e)

        return []

    def query_absent_requirements(self) -> list[dict[str, Any]]:
        """Return requirements with no UI coverage."""
        if self._driver:
            try:
                cypher = """
                MATCH (r:Requirement)
                WHERE r.coverage_status IN ['ABSENT', 'UNVERIFIED']
                RETURN r.id AS id, r.text AS text, r.category AS category,
                       r.coverage_status AS status, null AS closest_flow
                ORDER BY r.id
                """
                with self._driver.session() as session:
                    result = session.run(cypher)
                    return [dict(row) for row in result]
            except Exception as e:
                logger.warning("Neo4j absent-requirement query failed (%s)", e)

        return []

    def get_requirement_coverage_statuses(self, requirements: list[Requirement]) -> dict[str, str]:
        """Read current graph coverage only for the exact ingested sources.

        Requirement identifiers restart at REQ-001 for each ingestion.  Matching
        on both ID and source URL prevents a prior graph build from assigning a
        stale coverage result to a newly ingested, unrelated README.
        """
        self._require_driver()
        items = [{"id": req.id, "source_url": req.source_url} for req in requirements]
        cypher = """
        UNWIND $items AS item
        MATCH (r:Requirement {id: item.id, source_url: item.source_url})
        RETURN r.id AS id, r.coverage_status AS coverage_status
        """
        with self._driver.session() as session:
            result = session.run(cypher, items=items)
            return {
                record["id"]: record["coverage_status"]
                for record in result
                if record["coverage_status"] in {status.value for status in CoverageStatus}
            }

    def cypher_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run arbitrary Cypher (for API /graph/query endpoint)."""
        self._require_driver()
        with self._driver.session() as session:
            result = session.run(query, **(params or {}))
            return [dict(row) for row in result]

    # ─────────────────────────────────────────
    #  Full Build Pipeline
    # ─────────────────────────────────────────

    def load_transitions(self, transitions: list[Transition]) -> None:
        """TRANSITION_TO: Page -> Page (with trigger element and action label)"""
        cypher = """
        UNWIND $items AS item
        MATCH (p1:Page {id: item.from_page_id}), (p2:Page {id: item.to_page_id})
        MERGE (p1)-[r:TRANSITION_TO {id: item.id}]->(p2)
        SET r.action = item.action_label,
            r.interaction_type = item.interaction_type,
            r.trigger_element_id = item.trigger_element_id
        """
        if self._driver:
            try:
                with self._driver.session() as session:
                    session.run(cypher, items=[t.model_dump(mode="json") for t in transitions])
                logger.info("Loaded %d TRANSITION_TO edges", len(transitions))
            except Exception as e:
                logger.debug("Could not load transitions to Neo4j: %s", e)

    def build_graph(
        self,
        requirements: list[Requirement],
        flows: list[UserFlow] | None = None,
        pages: list[Page] | None = None,
        elements: list[UIElement] | None = None,
        transitions: list[Transition] | None = None,
        code_files: list[CodeFile] | None = None,
        code_symbols: list[CodeSymbol] | None = None,
        pr: PullRequest | None = None,
        changes: list[PRChange] | None = None,
    ) -> dict[str, int]:
        """
        Build the complete 3-layer graph.
        Returns node counts after build.
        """
        self._require_driver()
        flows = flows or []
        pages = pages or []
        elements = elements or []
        code_files = code_files or []
        code_symbols = code_symbols or []
        changes = changes or []

        logger.info("Building graph...")

        self.clear_active_evidence_graph()
        self.create_schema()

        # Layer 1: Requirements
        self.load_requirements(requirements)

        # Layer 2: UI
        self.load_flows(flows)
        self.load_pages(pages)
        self.load_ui_elements(elements)
        if transitions:
            self.load_transitions(transitions)

        # Layer 3: Code
        self.load_code_files(code_files)
        self.load_code_symbols(code_symbols)

        # PR
        if pr and changes:
            self.load_pull_request(pr, changes)

        # Edges
        self.create_page_flow_edges(pages, flows)
        self.create_element_page_edges(elements)
        self.create_flow_requirement_edges(flows)

        if code_symbols:
            self.create_symbol_file_edges(code_symbols)
            self.create_ui_code_edges_by_name(elements, code_symbols)

        if pr and changes and code_symbols:
            self.create_pr_symbol_edges(changes)

        # Cross-layer: Req → UI
        self.create_requirement_ui_edges(requirements, elements)
        self.create_observed_flow_requirement_edges()

        # Absence detection
        self.run_absence_detection(requirements)

        counts = self.get_node_counts()
        logger.info("Graph built: %s", counts)
        return counts

    def create_observed_flow_requirement_edges(self) -> None:
        """Link a flow to requirements only when the crawl contains matching evidence."""
        cypher = """
        MATCH (f:UserFlow)<-[:STEP_IN]-(p:Page)<-[:PART_OF]-(e:UIElement)<-[:COVERS]-(r:Requirement)
        MERGE (f)-[:REQUIRES {method: 'observed_ui_coverage'}]->(r)
        """
        with self._driver.session() as session:
            session.run(cypher)
