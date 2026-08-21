import asyncio
import sys

sys.path.insert(0, ".")
from app.code_analyzer import CodeAnalyzer
from app.config import get_settings
from app.ingestor import RequirementIngestor
from app.llm import MockLLMProvider


async def main():
    settings = get_settings()
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: ingest
    ingestor = RequirementIngestor(llm=MockLLMProvider(), data_dir=data_dir)
    reqs = await ingestor.run(use_seeds=True)
    print(f"Requirements: {len(reqs)}")

    # Step 2: fetch PR code
    analyzer = CodeAnalyzer(github_token=None, data_dir=data_dir)
    try:
        result = await analyzer.run("saleor/saleor-dashboard", 6857)
        changes = result["changes"]
        symbols = result["code_symbols"]
        print(f"Changed files: {len(changes)}")
        print(f"Symbols: {len(symbols)}")
        for s in symbols[:12]:
            print(f"  {s.fqn} ({s.symbol_type}, component={s.is_component}, hook={s.is_hook})")
    except Exception as e:
        print(f"Code fetch error: {e}")
        import traceback

        traceback.print_exc()


asyncio.run(main())
