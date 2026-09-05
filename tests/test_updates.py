from app.schemas.updates import (
    extract_chat_type,
    extract_forward_chat_id,
    extract_media_items,
    extract_unsupported_types,
    is_round_video,
    parse_message_callback,
)


def test_callback_parse():
    uid, cid, payload = parse_message_callback(
        {
            "callback": {
                "callback_id": "c1",
                "payload": "tab:tpl",
                "user": {"user_id": 7},
            }
        }
    )
    assert (uid, cid, payload) == (7, "c1", "tab:tpl")


def test_channel_type():
    upd = {
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {"mid": "m1", "text": ""},
        }
    }
    assert extract_chat_type(upd) == "channel"


def test_forward_chat():
    upd = {
        "message": {
            "link": {"type": "forward", "chat_id": 555},
            "body": {},
        }
    }
    assert extract_forward_chat_id(upd) == 555


def test_image_photos_map_is_one_item():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {
                        "type": "image",
                        "payload": {
                            "photos": {
                                "a": {"token": "t1", "url": "https://i.oneme.ru/a"},
                                "b": {"token": "t2"},
                            }
                        },
                    }
                ]
            }
        }
    }
    media = extract_media_items(upd)
    assert media == [
        ("photo", {"token": "t1", "url": "https://i.oneme.ru/a"}),
    ]


def test_file_without_suffix_is_photo():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "file", "payload": {"token": "raw"}},
                    {
                        "type": "file",
                        "payload": {"token": "pdf", "filename": "notes.pdf"},
                    },
                ]
            }
        }
    }
    items = extract_media_items(upd)
    assert items == [("photo", {"token": "raw"})]


def test_image_file_by_filename():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {
                        "type": "file",
                        "payload": {"token": "f1", "filename": "mark.png"},
                    },
                    {
                        "type": "file",
                        "payload": {"token": "f2", "filename": "notes.pdf"},
                    },
                ]
            }
        }
    }
    assert extract_media_items(upd) == [
        ("photo", {"token": "f1", "filename": "mark.png"}),
    ]


def test_native_image_and_png_file_are_both_kept():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "image", "payload": {"token": "img"}},
                    {
                        "type": "file",
                        "payload": {"token": "f1", "filename": "mark.png"},
                    },
                ]
            }
        }
    }
    assert extract_media_items(upd) == [
        ("photo", {"token": "img"}),
        ("photo", {"token": "f1", "filename": "mark.png"}),
    ]


def test_unsupported_sticker():
    upd = {
        "message": {
            "body": {"attachments": [{"type": "sticker", "payload": {"code": "x"}}]}
        }
    }
    assert extract_unsupported_types(upd) == ["sticker"]
    assert extract_media_items(upd) == []


def test_video_file_by_filename():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {
                        "type": "file",
                        "payload": {"token": "v1", "filename": "clip.mp4"},
                    },
                    {
                        "type": "file",
                        "payload": {"token": "p1", "filename": "notes.pdf"},
                    },
                ]
            }
        }
    }
    assert extract_media_items(upd) == [
        ("video", {"token": "v1", "filename": "clip.mp4"}),
    ]


def test_native_video_and_mp4_file_are_both_kept():
    upd = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "video", "payload": {"token": "vid"}},
                    {
                        "type": "file",
                        "payload": {"token": "v1", "filename": "clip.mp4"},
                    },
                ]
            }
        }
    }
    assert extract_media_items(upd) == [
        ("video", {"token": "vid"}),
        ("video", {"token": "v1", "filename": "clip.mp4"}),
    ]


def test_round_video_flag():
    assert is_round_video({"token": "t", "is_round": True})
    assert not is_round_video({"token": "t"})
    upd = {
        "message": {
            "body": {"attachments": [{"type": "video_note", "payload": {"token": "c"}}]}
        }
    }
    assert extract_unsupported_types(upd) == ["video_note"]
    round_native = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "video", "payload": {"token": "t", "is_round": True}}
                ]
            }
        }
    }
    assert extract_unsupported_types(round_native) == ["video_note"]
    assert extract_media_items(round_native) == []


def test_media_items_album_keeps_mixed_video_photo():
    album = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                    {
                        "type": "file",
                        "payload": {"token": "c", "filename": "c.png"},
                    },
                ]
            }
        }
    }
    kinds = [k for k, _ in extract_media_items(album)]
    assert kinds == ["photo", "photo", "photo"]
    mixed = {
        "message": {
            "body": {
                "attachments": [
                    {"type": "video", "payload": {"token": "vid"}},
                    {"type": "image", "payload": {"token": "pic"}},
                ]
            }
        }
    }
    items = extract_media_items(mixed)
    assert items == [
        ("video", {"token": "vid"}),
        ("photo", {"token": "pic"}),
    ]
