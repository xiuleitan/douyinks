from douyinks.sync_state import MatrixSyncState


def test_matrix_sync_state_persists_next_batch_token(tmp_path):
    path = tmp_path / "matrix_sync_state.json"
    state = MatrixSyncState(path)

    state.save_next_batch("token-1")

    assert MatrixSyncState(path).load_next_batch() == "token-1"


def test_matrix_sync_state_ignores_missing_token(tmp_path):
    assert MatrixSyncState(tmp_path / "missing.json").load_next_batch() is None
