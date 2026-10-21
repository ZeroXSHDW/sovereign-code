from calc import add


def test_add():
    assert add(1, 2) == 3
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
    assert add(100, 200) == 300

if __name__ == "__main__":
    test_add()
    print("Tests passed!")
