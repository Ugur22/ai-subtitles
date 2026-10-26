class IncompleteIndexError(RuntimeError):
    """Some image-embedding batches could not be written; the stored index is partial."""

    def __init__(self, indexed: int, expected: int):
        super().__init__(f"indexed {indexed}/{expected} images")
        self.indexed = indexed
        self.expected = expected
