from app.rag.engine import get_db_path, get_upload_dir


def test_rag_paths_are_scoped_by_knowledge_base_id():
    assert get_db_path("kb_a").endswith("/kb_a")
    assert get_upload_dir("kb_a").endswith("/kb_a")
    assert get_db_path("kb/../../evil").endswith("/kb_______evil")


def test_rag_paths_default_to_default_knowledge_base():
    assert get_db_path().endswith("/kb_default")
    assert get_upload_dir().endswith("/kb_default")
