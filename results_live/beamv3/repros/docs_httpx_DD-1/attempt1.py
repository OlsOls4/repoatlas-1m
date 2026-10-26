import httpx


def main():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<!doctype html>...",
            headers={"content-type": "text/html; charset=UTF-8"},
        )
    )
    original_get = httpx.get

    def get(url, *args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original_get(url, *args, **kwargs)

    httpx.get = get
    r = httpx.get("https://www.example.org/")  # DOC-LITERAL
    assert r.encoding == "UTF-8", "docs say r.encoding is 'UTF-8'"  # DOC-LITERAL
    print("DOCS_OK")


if __name__ == "__main__":
    main()
