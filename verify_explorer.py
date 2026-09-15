"""Read-only live explorer acceptance. Reuses existing chain records; creates no wallets or transactions."""
import json
import threading
from urllib.request import urlopen

from explorer import ExplorerServer


def verify():
    with ExplorerServer(0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def get(path):
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/{path}", timeout=30) as response:
                return json.load(response)

        try:
            overview = get("overview")
            assert overview["chain_id"] == "luxartium-local-1"
            assert overview["supply"]["denom"] == "uluxar"
            assert int(overview["height"]) > 0 and int(overview["validators"]) >= 1
            assert overview["blocks"]["items"]
            print("PASS live overview, native supply and validator count")
            before = overview["blocks"]["next_before"]
            if before:
                older = get("blocks?before=" + before)
                assert all(int(b["height"]) <= int(before) for b in older["items"])
                print("PASS older-block pagination")
            indexed = get("transactions")
            assert indexed["items"], "Run the documented demo transfer before this read-only verification."
            tx = get("tx/" + indexed["items"][0]["hash"])
            block = get("block/" + tx["tx_response"]["height"])
            assert tx["tx_response"]["txhash"] in block["transactions"]
            print("PASS transaction lookup and independently computed block transaction hash")
            message = next((m for m in tx["tx"]["body"]["messages"] if m["@type"] == "/cosmos.bank.v1beta1.MsgSend"), None)
            assert message is not None, "The latest indexed transaction must be a bank send for this demo check."
            account = get("account/" + message["from_address"])
            assert account["balance"]["denom"] == "uluxar" and isinstance(account["balance"]["amount"], str)
            assert any(row["hash"] == tx["tx_response"]["txhash"] for row in account["transactions"])
            print("PASS account balance and indexed sender history")
            print(json.dumps({"result": "PASS", "height": overview["height"],
                              "transaction": tx["tx_response"]["txhash"],
                              "account": account["address"], "balance": account["balance"]}, indent=2))
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    verify()
