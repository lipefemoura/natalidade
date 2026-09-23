import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()
CSV_PATH = Path(os.environ["CSV_PATH"])


def main() -> None:
    linhas = duckdb.sql(f"SELECT count(*) FROM '{CSV_PATH.as_posix()}'").fetchone()[0]
    print(f"{CSV_PATH}: {linhas} linhas")


if __name__ == "__main__":
    main()
