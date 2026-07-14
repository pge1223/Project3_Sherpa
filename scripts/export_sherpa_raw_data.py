"""
sherpa_mongo(kstartup_raw, bizinfo_raw)를 RAG 파이프라인 입력용으로
1회성 export한다. SSH 터널을 열어 접속하고, 컬렉션별로 data/raw/ 밑에
JSON 파일로 저장한다.

실행 전: 레포 루트 .env에 SHERPA_SSH_*, SHERPA_MONGO_* 값이 채워져 있어야 한다.
    python scripts/export_sherpa_raw_data.py
"""
import json
import os
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv

import paramiko
if not hasattr(paramiko, "DSSKey"):
    paramiko.DSSKey = paramiko.RSAKey  # sshtunnel <-> 최신 paramiko 호환용

from sshtunnel import SSHTunnelForwarder
from pymongo import MongoClient

load_dotenv()

SSH_HOST = os.getenv("SHERPA_SSH_HOST")
SSH_USER = os.getenv("SHERPA_SSH_USER")
SSH_PASSWORD = os.getenv("SHERPA_SSH_PASSWORD")

MONGO_USER = os.getenv("SHERPA_MONGO_USER")
MONGO_PASSWORD = os.getenv("SHERPA_MONGO_PASSWORD")
MONGO_AUTH_SOURCE = os.getenv("SHERPA_MONGO_AUTH_SOURCE", "admin")
MONGO_DB = os.getenv("SHERPA_MONGO_DB", "sherpa_mongo")

COLLECTIONS = ["kstartup_raw", "bizinfo_raw"]
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)


def main():
    if not all([SSH_HOST, SSH_USER, SSH_PASSWORD, MONGO_USER, MONGO_PASSWORD]):
        raise SystemExit("SHERPA_SSH_*, SHERPA_MONGO_* 환경변수를 .env에 먼저 채워주세요.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with SSHTunnelForwarder(
        (SSH_HOST, 22),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASSWORD,
        remote_bind_address=("localhost", 27017),
    ) as tunnel:
        client = MongoClient(
            f"mongodb://localhost:{tunnel.local_bind_port}",
            username=MONGO_USER,
            password=MONGO_PASSWORD,
            authSource=MONGO_AUTH_SOURCE,
            directConnection=True,
            serverSelectionTimeoutMS=5000,
        )
        db = client[MONGO_DB]

        for name in COLLECTIONS:
            docs = list(db[name].find({}))
            out_path = OUTPUT_DIR / f"{name}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(docs, f, ensure_ascii=False, indent=2, cls=MongoJSONEncoder)
            print(f"{name}: {len(docs)}건 -> {out_path}")

        client.close()


if __name__ == "__main__":
    main()
