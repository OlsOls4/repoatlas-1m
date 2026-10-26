import httpx


def main():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<!doctype html>...",
            headers={"content-type": "text/html; charset=UTF-8"},
        )
    )
    client = httpx.Client(transport=transport)
    httpx.get = client.get

    r = httpx.get("https://www.example.org/")  # DOC-LITERAL
    assert r.encoding == "UTF-8", "docs say r.encoding is 'UTF-8'"  # DOC-LITERAL
    print("DOCS_OK")


if __name__ == "__main__":
    main()
