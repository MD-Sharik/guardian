"""Greets the world."""


def greet(name: str = "world") -> str:
    return f"Helo, {name}!"


if __name__ == "__main__":
    print(greet())
