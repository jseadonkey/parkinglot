from parking_crew.langfuse_config import langfuse_base_url


def test_langfuse_base_url_is_us_hardwired() -> None:
    assert langfuse_base_url() == "https://us.cloud.langfuse.com"
