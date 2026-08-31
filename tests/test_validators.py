from app.validators import require_numbers


def test_accepts_valid_numbers():
    require_numbers(1, 2.5, -3)  # should not raise


def test_rejects_non_number():
    try:
        require_numbers(1, "not a number")
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_rejects_bool_as_number():
    # bool is technically a subclass of int in Python — explicitly rejected
    # since "True" as a calculator operand is a real edge case worth
    # catching, not silently treating True as 1.
    try:
        require_numbers(1, True)
        assert False, "expected TypeError"
    except TypeError:
        pass
