"""Preset Genre and Language lists, used to populate dropdowns in Book
Details and the library's Genre/Language filter bar. Any custom value a
user types is preserved and shown alongside these -- these are just a
helpful, comprehensive starting point, not a hard restriction.
"""

GENRE_PRESETS = [
    "Fiction", "Non-Fiction", "Science Fiction", "Fantasy", "Mystery",
    "Thriller", "Horror", "Romance", "Historical Fiction", "Adventure",
    "Classic Literature", "Literary Fiction", "Young Adult", "Children's",
    "Poetry", "Drama", "Biography", "Autobiography", "Memoir", "History",
    "Philosophy", "Religion & Spirituality", "Self-Help", "Psychology",
    "Business", "Economics", "Science", "Technology", "Computers & Programming",
    "Mathematics", "Health & Fitness", "Cooking", "Travel",
    "Art & Photography", "Music", "Sports", "Comics & Graphic Novels",
    "Reference", "True Crime", "Politics", "Education", "Law",
]

LANGUAGE_PRESETS = [
    "English", "Spanish", "French", "German", "Italian", "Portuguese",
    "Russian", "Chinese", "Japanese", "Korean", "Arabic", "Hindi",
    "Bengali", "Bulgarian", "Dutch", "Swedish", "Norwegian", "Danish",
    "Finnish", "Polish", "Czech", "Slovak", "Hungarian", "Romanian",
    "Greek", "Turkish", "Hebrew", "Ukrainian", "Vietnamese", "Thai",
    "Indonesian", "Persian", "Urdu", "Serbian", "Croatian", "Latin",
]


def merge_with_used(presets, used_values):
    """Combine a preset list with whatever additional values are actually
    in use across the library -- a custom genre/language someone typed in
    Book Details, or one an imported filename already encoded -- so every
    place that offers genres/languages (the filter bar, Book Details, and
    the right-click bulk "Set Genre/Language") shows the same full picture
    instead of the presets alone.

    A used value that only differs from a preset by capitalization is
    treated as that preset (e.g. "fantasy" collapses into "Fantasy").
    Among the non-preset values, entries differing only by capitalization
    are folded into a single option too, so near-duplicates typed at
    different times don't show up as separate checkboxes -- whichever
    casing was encountered first is kept. Passing an empty preset list
    turns this into a plain case-insensitive dedupe of `used_values`,
    which is also useful for a fully freeform field like Series.
    """
    preset_lower = {p.lower() for p in presets}
    extras = {}  # lowercase -> first-seen original casing
    for v in used_values:
        v = (v or "").strip()
        if not v or v.lower() in preset_lower:
            continue
        extras.setdefault(v.lower(), v)
    return list(presets) + sorted(extras.values(), key=str.lower)


def normalize_custom_value(text, known_values):
    """Normalize a freely-typed Series/Genre/Language value so different
    capitalizations of the same word don't create separate near-duplicate
    entries later. If `text` case-insensitively matches something already
    in `known_values`, that value's existing casing is reused -- typing
    "fantasy" when "Fantasy" is already in use becomes "Fantasy" rather
    than adding a second, differently-cased entry. If it's genuinely new,
    each word's first letter is capitalized and the rest of the word is
    left alone -- unlike str.title(), this doesn't lowercase the rest of a
    word (so "USA" stays "USA") and doesn't mangle apostrophes (so
    "children's" doesn't become "Children'S")."""
    text = (text or "").strip()
    if not text:
        return text

    lower_map = {}
    for v in known_values:
        v = (v or "").strip()
        if v:
            lower_map.setdefault(v.lower(), v)
    match = lower_map.get(text.lower())
    if match:
        return match

    def cap_word(word):
        for i, ch in enumerate(word):
            if ch.isalpha():
                return word[:i] + ch.upper() + word[i + 1:]
        return word

    return " ".join(cap_word(w) for w in text.split(" "))
