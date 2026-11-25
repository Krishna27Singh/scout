from httpx import AsyncClient


async def test_frontend_shell_and_static_assets_are_served(client: AsyncClient) -> None:
    page = await client.get("/")
    styles = await client.get("/static/styles.css")
    script = await client.get("/static/app.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-cache"
    assert "Scout" in page.text
    assert 'id="chat-log"' in page.text
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert styles.headers["cache-control"] == "no-cache"
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert script.headers["cache-control"] == "no-cache"
