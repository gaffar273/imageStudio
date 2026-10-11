"""UI-independent progress callback used by rendering workflows."""


class Progress:
    def __call__(self, value=None, desc=None, **kwargs):
        pass
