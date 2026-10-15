import requests


class LockProviderClient:
    base_url = "https://api.lockprovider.example/v1"

    def create_code(self, lock_id, code, starts_at, ends_at):
        resp = requests.post(
            f"{self.base_url}/locks/{lock_id}/codes",
            json={"code": code, "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["id"]
