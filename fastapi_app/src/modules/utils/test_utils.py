# テスト用ユーティリティモジュール

class TestUtils():
    def test_generate_uuid(self):
        """ UUID生成ユーティリティのテスト """
        from . import generate_uuid
        # UUIDがユニークであることと、長さが36であることを確認
        uuid1, uuid2 = generate_uuid(), generate_uuid()
        assert uuid1 != uuid2, "生成されたUUIDが重複しています"
        assert len(uuid1) == 36, "生成されたUUIDの長さが不正です"
        assert len(uuid2) == 36, "生成されたUUIDの長さが不正です"