from app.ocr import lines_from_winocr


def test_winocr_result_converts_to_line_boxes():
    result = {
        "lines": [
            {
                "text": "Beta blockers lower heart rate.",
                "words": [
                    {"text": "Beta", "bounding_rect": {"x": 10, "y": 20, "width": 30, "height": 18}},
                    {"text": "blockers", "bounding_rect": {"x": 45, "y": 21, "width": 60, "height": 18}},
                    {"text": "lower", "bounding_rect": {"x": 110, "y": 20, "width": 40, "height": 18}},
                    {"text": "heart", "bounding_rect": {"x": 155, "y": 20, "width": 40, "height": 18}},
                    {"text": "rate.", "bounding_rect": {"x": 200, "y": 20, "width": 35, "height": 18}},
                ],
            }
        ]
    }
    lines = lines_from_winocr(result, 600)
    assert len(lines) == 1
    line = lines[0]
    assert line["text"] == "Beta blockers lower heart rate."
    assert (line["x0"], line["y0"], line["x1"], line["y1"]) == (10.0, 20.0, 235.0, 39.0)


def test_winocr_result_ignores_entries_without_boxes():
    result = {"lines": [{"text": "orphan text", "words": []}]}
    assert lines_from_winocr(result, 600) == []


def test_winocr_result_orders_columns():
    def line(text, x, y):
        return {
            "text": text,
            "words": [
                {
                    "text": text,
                    "bounding_rect": {"x": x, "y": y, "width": 300, "height": 20},
                }
            ],
        }

    result = {
        "lines": [
            line("right 0", 520, 100),
            line("left 0", 40, 100),
            line("right 1", 520, 130),
            line("left 1", 40, 130),
            line("right 2", 520, 160),
            line("left 2", 40, 160),
            line("right 3", 520, 190),
            line("left 3", 40, 190),
        ]
    }
    assert [entry["text"] for entry in lines_from_winocr(result, 1000)] == [
        "left 0",
        "left 1",
        "left 2",
        "left 3",
        "right 0",
        "right 1",
        "right 2",
        "right 3",
    ]
