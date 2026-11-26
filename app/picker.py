"""Native file picker for selecting files on the local machine."""

from __future__ import annotations


class PickerError(RuntimeError):
    pass


def pick_files() -> list[str]:
    """Open the Windows file dialog and return selected absolute paths."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - tkinter is in the stdlib on Windows
        raise PickerError(f"Couldn't load the file picker: {exc}") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        selected = filedialog.askopenfilenames(
            parent=root,
            title="Add files to Anki Scribe",
            filetypes=[
                (
                    "Books, lectures and transcripts",
                    "*.pdf *.epub *.pptx *.png *.jpg *.jpeg *.webp *.srt *.vtt *.txt *.md",
                ),
                ("PDF", "*.pdf"),
                ("EPUB books", "*.epub"),
                ("PowerPoint", "*.pptx"),
                ("Images", "*.png *.jpg *.jpeg *.webp"),
                ("Transcripts", "*.srt *.vtt *.txt *.md"),
                ("All files", "*.*"),
            ],
        )
        return [str(path) for path in selected]
    except Exception as exc:  # pragma: no cover - depends on local GUI session
        raise PickerError(f"Couldn't open the file picker: {exc}") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
