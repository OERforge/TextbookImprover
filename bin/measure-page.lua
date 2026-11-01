-- measure-page.lua: what build-pdf.py's measure_page reads of a book's page
-- and faces, in LuaLaTeX, for the PDF filter's counts (pdf-target.lua's
-- MEASURES): the line's width and the space between two of a table's
-- columns, in ems of the text's type; the width of each of the text face's
-- printable ASCII characters, its space the first, and in bold; its small
-- letters, each as often as in English, for a character outside ASCII; its
-- space; a character of code; a list's margins in a table's cell, at each
-- depth, and its label space; a note's mark; and the width of each formula
-- count-formulas.txt lists. Loaded by the
-- document measure_page writes, which calls each function in turn and
-- reads the line report writes.

oer_measure = { widths = {} }

-- How often each letter is in English, per hundred letters.
local FREQUENCY = {
  e = 12.7, t = 9.1, a = 8.2, o = 7.5, i = 7.0, n = 6.7, s = 6.3, h = 6.1, r = 6.0,
  d = 4.3, l = 4.0, c = 2.8, u = 2.8, m = 2.4, w = 2.4, f = 2.2, g = 2.0, y = 2.0,
  p = 1.9, b = 1.5, v = 1.0, k = 0.8, j = 0.15, x = 0.15, q = 0.1, z = 0.07,
}

local function current()
  return font.getfont(font.current())
end

-- A character's width in the font, in ems of size; 0 where it has none.
local function width(f, c, size)
  local glyph = f.characters[utf8.codepoint(c)]
  return glyph and glyph.width / size or 0
end

-- The text face, set when this is called: its size is the em the rest are
-- measured in. line and gap in scaled points, \linewidth and \tabcolsep.
function oer_measure.text(line, gap)
  local f = current()
  local size = f.size
  local lower, total = 0, 0
  for letter, share in pairs(FREQUENCY) do
    lower = lower + share * width(f, letter, size)
    total = total + share
  end
  local chars = {}
  for code = 32, 126 do
    chars[#chars + 1] = string.format("%.4f", code == 32 and f.parameters.space / size
                                                or width(f, string.char(code), size))
  end
  oer_measure.chars = chars
  oer_measure.size = size
  oer_measure.text_ = {
    line = line / size, gap = 2 * gap / size, lower = lower / total,
    space = f.parameters.space / size, points = line / 65536,
  }
end

-- Code's face, set when this is called: one of its characters, an x.
function oer_measure.mono()
  oer_measure.mono_ = width(current(), "x", oer_measure.size)
end

-- The text face in bold, set when this is called: each printable ASCII
-- character's width, in ems of the text's size, its space the first, for
-- bold text in a table's cell and a description list's term, which LaTeX
-- sets in bold.
function oer_measure.bold()
  local f = current()
  local chars = {}
  for code = 32, 126 do
    chars[#chars + 1] = string.format("%.4f", code == 32 and f.parameters.space / oer_measure.size
                                                or width(f, string.char(code), oer_measure.size))
  end
  oer_measure.bold_ = chars
end

-- A list's label space, \labelsep, called with it, in scaled points: what
-- separates a description list's term from its definition.
function oer_measure.labelsep(sep)
  oer_measure.labelsep_ = sep / oer_measure.size
end

-- How much narrower a list's line is than the line it's in, its margins
-- together, at each depth a table's cell can hold, called inside the list
-- with \hsize and \linewidth: in a minipage, as the writer sets a cell
-- that holds a list, where LaTeX counts a list's depth from the first
-- again. Called at each depth in turn, from the first.
function oer_measure.list(hsize, linewidth)
  local lists = oer_measure.lists_ or {}
  lists[#lists + 1] = (hsize - linewidth) / oer_measure.size
  oer_measure.lists_ = lists
end

-- A note's mark as LaTeX sets it (\@makefnmark: the note's number in a
-- superscript's type, raised, \scriptspace after it), called with its
-- width, in scaled points, for each of the first nine notes as the book
-- numbers them (\thefootnote: a number, a letter, or a symbol, as
-- \fnsymbol's doubled ones from the seventh).
function oer_measure.note(w)
  oer_measure.note_ = math.max(oer_measure.note_ or 0, w / oer_measure.size)
end

-- A mark of a digit and of two of it, called with their widths, in
-- scaled points, for each digit in turn: a digit's advance in a mark, the
-- widest, for a mark of more digits, and the widest mark of one, which
-- the first nine's may be narrower than.
function oer_measure.notedigit(one, two)
  local size = oer_measure.size
  oer_measure.notedigit_ = math.max(oer_measure.notedigit_ or 0, (two - one) / size)
  oer_measure.noteone_ = math.max(oer_measure.noteone_ or 0, one / size)
end

-- A formula's width, in scaled points, as LaTeX set it in text style.
function oer_measure.formula(w)
  local widths = oer_measure.widths
  widths[#widths + 1] = w / oer_measure.size
end

-- The line build-pdf.py reads, written to the file named: key=value
-- pairs, separated by semicolons, the formulas' widths after math=,
-- separated by commas. To a file, since TeX would break a line this long
-- in its log. The line, the space between two columns, a character of
-- code, and a list's margins to six places, which a column held at a word
-- of code is as wide as to the scaled point (pdf-target.lua's held_part):
-- to four, a face whose character of code is a fraction of an em with
-- more places, rounded down, had a word of forty such characters counted
-- a fiftieth of a point narrower than it is.
function oer_measure.report(name)
  local t = oer_measure.text_
  local parts = {}
  for _, key in ipairs({ "line", "gap", "lower", "space", "points" }) do
    parts[#parts + 1] = key .. "=" .. string.format("%.6f", t[key])
  end
  parts[#parts + 1] = "mono=" .. string.format("%.6f", oer_measure.mono_ or 0)
  local lists = {}
  for i, w in ipairs(oer_measure.lists_ or {}) do lists[i] = string.format("%.6f", w) end
  parts[#parts + 1] = "lists=" .. table.concat(lists, ",")
  parts[#parts + 1] = "labelsep=" .. string.format("%.6f", oer_measure.labelsep_ or 0)
  -- A note's mark of one digit, the widest of the first nine's as the
  -- book numbers them and of a digit's, and a digit's advance in a mark,
  -- which a mark of more digits is wider by for each: "(9)", then "(99)".
  parts[#parts + 1] = "note=" .. string.format("%.6f,%.6f",
    math.max(oer_measure.note_ or 0, oer_measure.noteone_ or 0), oer_measure.notedigit_ or 0)
  parts[#parts + 1] = "chars=" .. table.concat(oer_measure.chars, ",")
  parts[#parts + 1] = "bold=" .. table.concat(oer_measure.bold_ or {}, ",")
  local widths = {}
  for i, w in ipairs(oer_measure.widths) do widths[i] = string.format("%.4f", w) end
  parts[#parts + 1] = "math=" .. table.concat(widths, ",")
  local out = io.open(name, "w")
  out:write(table.concat(parts, ";"), "\n")
  out:close()
end
