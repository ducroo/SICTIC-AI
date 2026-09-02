import json

from lib.people.linkedin.store import LinkedInProfileStore


class _MemoryStorage:
    def __init__(self, files=None):
        self.files = files or {}

    def exists(self, path):
        return path in self.files or any(
            name.startswith(f"{path}/") for name in self.files
        )

    def list(self, path, suffix=""):
        prefix = f"{path}/"
        return [
            name.removeprefix(prefix)
            for name in self.files
            if name.startswith(prefix) and name.endswith(suffix)
        ]

    def read_text(self, path):
        return self.files[path]

    def mkdir(self, _path):
        pass

    def write_text(self, path, content):
        self.files[path] = content


def test_profile_store_cleans_new_profiles_before_writing():
    storage = _MemoryStorage()
    store = LinkedInProfileStore(storage, "profiles")

    stored = store.write(
        "jane-doe",
        {
            "fullName": "Jane Doe",
            "profileUrl": "https://linkedin.com/in/jane-doe",
        },
    )

    assert stored == {"fullName": "Jane Doe"}
    assert json.loads(storage.files["profiles/jane-doe.json"]) == stored
