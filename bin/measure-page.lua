-- measure-page.lua: what build-pdf.py's measure_page reads of a book's page
-- and faces, in LuaLaTeX, for the PDF filter's counts (pdf-target.lua's
-- MEASURES): the line's width and the space between two of a table's
-- columns, in ems of the text's type; the width of each of the text face's
-- printable ASCII characters, its space the first; its small letters, each
-- as often as in English, for a character outside ASCII; its space; a
-- character of code; and the width of each formula count-formulas.txt
-- lists. Loaded by the document measure_page writes, which calls each
-- function in turn and reads the line report writes.

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

-- A formula's width, in scaled points, as LaTeX set it in text style.
function oer_measure.formula(w)
  local widths = oer_measure.widths
  widths[#widths + 1] = w / oer_measure.size
end

-- The line build-pdf.py reads, written to the file named: key=value
-- pairs, separated by semicolons, the formulas' widths after math=,
-- separated by commas. To a file, since TeX would break a line this long
-- in its log.
function oer_measure.report(name)
  local t = oer_measure.text_
  local parts = {}
  for _, key in ipairs({ "line", "gap", "lower", "space", "points" }) do
    parts[#parts + 1] = key .. "=" .. string.format("%.4f", t[key])
  end
  parts[#parts + 1] = "mono=" .. string.format("%.4f", oer_measure.mono_ or 0)
  parts[#parts + 1] = "chars=" .. table.concat(oer_measure.chars, ",")
  local widths = {}
  for i, w in ipairs(oer_measure.widths) do widths[i] = string.format("%.4f", w) end
  parts[#parts + 1] = "math=" .. table.concat(widths, ",")
  local out = io.open(name, "w")
  out:write(table.concat(parts, ";"), "\n")
  out:close()
end
