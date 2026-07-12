from autoapply.adapters.base import ADAPTERS, FillAction, adapter_for


def test_fill_action_is_frozen():
    action = FillAction(kind="css", target="#email", value="a@b.com")
    try:
        action.value = "other"
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_adapter_for_unknown_url_returns_none():
    assert adapter_for("https://careers.example.com/apply/1") is None


def test_registry_is_a_list():
    assert isinstance(ADAPTERS, list)
