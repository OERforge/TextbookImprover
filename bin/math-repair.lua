-- math-repair.lua -- math the source wrote in the wrong characters, or as
-- text. Run at the filter stage after figures-and-tables.lua, so every
-- target gets the repaired page: MathML in HTML and EPUB, LaTeX math in
-- the PDF, an equation in Word, $...$ in Markdown.
--
-- Three things, each with a setting to turn it off:
--
-- 1. Inside an equation (math.repair_equations). Word's equation editor
--    lets an author type a character that looks right and means something
--    else, and the statistics textbook does it hundreds of times: the micro
--    sign for mu, the increment sign for Delta, an en dash for minus (a
--    screen reader says "en dash"), a bar over x written as an en dash or
--    a macron set over it, y-hat as one precomposed character, and a null
--    hypothesis's zero as a slashed O. Each has one right form. The micro
--    sign, y-hat, and the slashed O are also characters no math font in
--    LaTeX maps, so the PDF dropped them. An equation's own text (\text{})
--    gets its en dashes made minus signs where the text is math, as the
--    economics textbook types its equations as text (text_minus).
--
-- 2. Math typed as text (math.from_text): italic letters, Greek, digits,
--    sub- and superscripts, and a relation between them, written as
--    ordinary text rather than as an equation. A screen reader reads the
--    superscript in "sigma 2" as nothing at all. Conservative on purpose,
--    since text isn't math until it's clearly math:
--      - an expression needs a relation (= < > and the rest) with an
--        operand on each end, and a variable: an italic Latin letter, a
--        Greek letter, or an equation already there. A plain Latin letter
--        is a word and ends the run, except a single one right before a
--        parenthesis, a function's name (P in P(x < 5)), and one right
--        before a sub- or superscript, the letter it's set on (n in n sub 1
--        = 4), which is a variable there; but a run ending in such a
--        letter's script that runs into a letter is a formula's (2H sub 2
--        O), and stays text. A comma and a space end a run outside
--        parentheses, and a colon and a space one with no variable yet, a
--        label's (Plan 1:).
--      - a lone symbol is a Greek letter, or an italic letter carrying a
--        sub- or superscript (H sub 0). A lone italic letter is left
--        alone: outside a statistics book it's mostly emphasis, an
--        initial, a letter of an italic title.
--    Measured on the statistics textbook and six other books of the test
--    corpus before this was written: the pattern held for math, and the
--    one false positive (a year range in a reference, 1773-1799) had no
--    variable, which the rules above require.
--
-- 3. A minus sign typed as an en dash in text (math.minus_in_text): a
--    negative number's sign, and a difference's in a run of arithmetic
--    with a relation in it, made a minus sign, since a screen reader
--    reads an en dash as nothing or as a range. The rules are at the
--    section's head.
--
-- Every change is a row in the report convert.py collects
-- (MATH_REPAIRED): its kind, the page, the text before, the TeX after.
-- A row copied from there into the math-keep sidecar (MATH_KEEP: Kind,
-- Page, Before; a blank Page is every page) keeps that one as it was:
-- the equation unrepaired, or the text left text. Each row that keeps
-- something is recorded (MATH_KEPT), so a row that matches nothing, since
-- the source changed, can be said to.
--
-- Copyright 2026 Robert Szarka
--
-- This program is free software: you can redistribute it and/or modify
-- it under the terms of the GNU General Public License as published by
-- the Free Software Foundation, either version 3 of the License, or
-- any later version.
--
-- This program is distributed in the hope that it will be useful,
-- but WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
-- GNU General Public License for more details.
--
-- You should have received a copy of the GNU General Public License
-- along with this program.  If not, see <https://www.gnu.org/licenses/>.

local function setting(name)
  return (os.getenv(name) or 'true'):lower() ~= 'false'
end

local REPAIR = setting('MATH_REPAIR_EQUATIONS')
local FROM_TEXT = setting('MATH_FROM_TEXT')
local REPORT = os.getenv('MATH_REPAIRED')
-- Where each text-made equation is, for writing it into a Word source
-- (format: source): the paragraph's text as the source gives it, with an
-- equation already there as one placeholder character, the equation's
-- text, which occurrence of it in the paragraph, and its TeX.
local KEEP = os.getenv('MATH_KEEP')
local KEPT = os.getenv('MATH_KEPT')
local PLACES = os.getenv('MATH_PLACES')
local PLACEHOLDER = '\u{FFFC}'

local page = ''
if PANDOC_STATE and PANDOC_STATE.input_files and PANDOC_STATE.input_files[1] then
  page = PANDOC_STATE.input_files[1]:match('([^/\\]+)$') or ''
  page = page:gsub('%.filtered%.json$', ''):gsub('%.[^.]+$', '')
end

-- ------------------------------------------------------------------------
-- the report

local report_handle

local function csv(value)
  value = tostring(value or '')
  if value:find('[",\n\r]') then
    return '"' .. value:gsub('"', '""') .. '"'
  end
  return value
end

local function report(kind, before, after)
  if not REPORT or REPORT == '' then return end
  if report_handle == nil then
    report_handle = io.open(REPORT, 'a') or false
  end
  if report_handle then
    report_handle:write(table.concat({csv(kind), csv(page), csv(before),
                                      csv(after)}, ',') .. '\n')
  end
end

-- The keep sidecar, as {kind: {before: {page = true}}}, a blank page
-- stored as the empty string.
local function parse_csv(text)
  text = text:gsub('\r\n', '\n'):gsub('\r', '\n')
  -- Excel's byte-order mark, at the file's start and at a line's, where
  -- appending math-repaired.csv, its header row and all, leaves one.
  text = '\n' .. text
  local marks
  repeat text, marks = text:gsub('\n\239\187\191', '\n') until marks == 0
  text = text:sub(2)
  local rows, row, field, quoted = {}, {}, {}, false
  local i, n = 1, #text
  local function end_field() row[#row + 1] = table.concat(field); field = {} end
  local function end_row()
    end_field()
    if #row > 1 or row[1] ~= '' then rows[#rows + 1] = row end
    row = {}
  end
  while i <= n do
    local c = text:sub(i, i)
    if quoted then
      if c == '"' then
        if text:sub(i + 1, i + 1) == '"' then
          field[#field + 1] = '"'
          i = i + 1
        else
          quoted = false
        end
      else
        field[#field + 1] = c
      end
    elseif c == '"' and #field == 0 then quoted = true
    elseif c == ',' then end_field()
    elseif c == '\n' then end_row()
    else field[#field + 1] = c end
    i = i + 1
  end
  if #field > 0 or #row > 0 then end_row() end
  return rows
end

local keep = {}
if KEEP and KEEP ~= '' then
  local handle = io.open(KEEP, 'r')
  if handle then
    for _, row in ipairs(parse_csv(handle:read('a'))) do
      local kind, where, before = row[1] or '', row[2] or '', row[3] or ''
      -- A header row anywhere: appending the report carries one along.
      if kind:lower() ~= 'kind' and before ~= '' then
        keep[kind] = keep[kind] or {}
        keep[kind][before] = keep[kind][before] or {}
        keep[kind][before][where] = true
      end
    end
    handle:close()
  end
end

local kept_handle

-- Whether the keep sidecar keeps this one, recording the row it matched.
local function kept(kind, before)
  local pages = keep[kind] and keep[kind][before]
  if not pages then return false end
  local where = pages[page] and page or (pages[''] and '' or nil)
  if not where then return false end
  if KEPT and KEPT ~= '' then
    if kept_handle == nil then kept_handle = io.open(KEPT, 'a') or false end
    if kept_handle then
      kept_handle:write(table.concat({csv(kind), csv(where), csv(before)}, ',') .. '\n')
    end
  end
  return true
end

local places_handle
-- Paragraphs can share a text, their equations differing only inside
-- the placeholders; each recorded paragraph's number in the page tells
-- them apart, in the order the Word file has them.
local paragraph_number = 0

local function place(number, paragraph, span, occurrence, tex)
  if not PLACES or PLACES == '' then return end
  if places_handle == nil then
    places_handle = io.open(PLACES, 'a') or false
  end
  if places_handle then
    places_handle:write(table.concat({csv(page), csv(number), csv(paragraph),
                                      csv(span), csv(occurrence), csv(tex)}, ',')
                        .. '\n')
  end
end

-- A paragraph's text as the Word file holds it: what's typed, spaces for
-- breaks, a placeholder for an equation, nothing for a note or an image.
local function inline_text(el)
  local t = el.t
  if t == 'Str' or t == 'Code' then return el.text end
  if t == 'Space' or t == 'SoftBreak' or t == 'LineBreak' then return ' ' end
  if t == 'Math' then return PLACEHOLDER end
  if t == 'Note' or t == 'Image' or t == 'RawInline' then return '' end
  if el.content then
    local out = {}
    for _, c in ipairs(el.content) do out[#out + 1] = inline_text(c) end
    return table.concat(out)
  end
  return ''
end

local function normalize(s)
  return (s:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', ''))
end

-- How many times needle occurs in haystack, plain, not overlapping.
local function occurrences(haystack, needle)
  local n, start = 0, 1
  while true do
    local i, j = haystack:find(needle, start, true)
    if not i then return n end
    n, start = n + 1, j + 1
  end
end

-- ------------------------------------------------------------------------
-- 1. inside an equation

local function replace_plain(s, old, new)
  local out, start = {}, 1
  while true do
    local i, j = s:find(old, start, true)
    if not i then break end
    out[#out + 1] = s:sub(start, i - 1)
    out[#out + 1] = new
    start = j + 1
  end
  out[#out + 1] = s:sub(start)
  return table.concat(out)
end

-- In order: the bars first, since one of them is an en dash. A fix marked
-- text is one character for another, and applies inside \text{...} too;
-- the others write a command, which text can't hold.
local EQUATION_FIXES = {
  {'\\overset{\u{00AF}}{', '\\bar{'},   -- a macron set over a letter
  {'\\overset{\u{2013}}{', '\\bar{'},   -- an en dash set over a letter
  {'\u{00B5}', '\u{03BC}', text = true}, -- micro sign for mu
  {'\u{2206}', '\u{0394}', text = true}, -- increment for capital Delta
  {'\u{0177}', '\\hat{y}'},             -- y-hat, one character
  {'\u{0176}', '\\hat{Y}'},
  {'_{\u{00D8}}', '_{0}'},              -- H sub slashed-O for H sub zero
  {'\u{00B7}', '\\cdot '},              -- middle dot for a product
}

-- Where a \text{...} was set aside while the rest is repaired.
local TEXT_OPEN, TEXT_CLOSE = '\u{E000}', '\u{E001}'

-- A letter or a digit beside an en dash in an equation's text.
local function text_letter(cp)
  return (cp >= 65 and cp <= 90) or (cp >= 97 and cp <= 122)
    or (cp >= 0xC0 and cp <= 0x24F and cp ~= 0xD7 and cp ~= 0xF7)
    or (cp >= 0x370 and cp <= 0x3FF)
end
local function text_digit(cp) return cp >= 48 and cp <= 57 end

-- An en dash in an equation's own text is a minus sign there too, where
-- the text is math, as an equation typed as text is: a number's sign
-- (\text{–1}), a charge's (\text{Cl}^{\text{–}}), or a difference
-- (\text{16~–~2P}, as the economics book types its equations). It stays
-- a dash between two letters with nothing between them, a bond
-- (\text{H–Cl}), between two digits so, a range, and beside another dash
-- (\text{–––}). Written as a minus sign in the text; a text that
-- holds nothing but the dash, and space, is the operator itself (body
-- returned as nil, and the dash in its place). body has its braces.
local TEXT_SPACE = {[32] = true, [126] = true, [0xA0] = true}

local function text_minus(body)
  local cps = {}
  for _, cp in utf8.codes(body) do cps[#cps + 1] = cp end
  local alone = true
  for i, cp in ipairs(cps) do
    local edge = (i == 1 and cp == 123) or (i == #cps and cp == 125)
    local escaped_space = cp == 92 and cps[i + 1] == 32
    local after_escape = cp == 32 and cps[i - 1] == 92
    if cp ~= 0x2013 and not (edge or TEXT_SPACE[cp] or escaped_space or after_escape) then
      alone = false
    end
  end
  local dashes = 0
  for i, cp in ipairs(cps) do
    if cp == 0x2013 then
      dashes = dashes + 1
      local a, b = cps[i - 1] or 0, cps[i + 1] or 0
      if not ((text_letter(a) and text_letter(b)) or (text_digit(a) and text_digit(b))
              or a == 0x2013 or b == 0x2013) then
        cps[i] = 0x2212
      end
    end
  end
  if alone and dashes == 1 then return nil end
  local out = {}
  for i, cp in ipairs(cps) do out[i] = utf8.char(cp) end
  return table.concat(out)
end

-- A text set over or under something as its mark (\underset{\text{–}}),
-- an underline a book draws so, isn't a sign.
local function a_mark(tex, position)
  local before = tex:sub(1, position - 1)
  return before:match('\\underset{$') or before:match('\\overset{$')
end

local function repair_tex(tex)
  -- \text{...} is set aside and given only the fixes marked text, and its
  -- en dashes made minus signs where the text is math (text_minus); its
  -- middle dots and y-hats stay characters, since \text{\cdot} is an error
  -- and the equation would be shown as TeX.
  local texts = {}
  local fixed = tex:gsub('()\\text(%b{})', function(position, body)
    for _, pair in ipairs(EQUATION_FIXES) do
      if pair.text then body = replace_plain(body, pair[1], pair[2]) end
    end
    if not a_mark(tex, position) then
      local signed_body = text_minus(body)
      if signed_body == nil then return '\u{2013}' end
      body = signed_body
    end
    texts[#texts + 1] = body
    return '\\text' .. TEXT_OPEN .. #texts .. TEXT_CLOSE
  end)
  for _, pair in ipairs(EQUATION_FIXES) do
    fixed = replace_plain(fixed, pair[1], pair[2])
  end
  -- An en dash is a minus.
  fixed = replace_plain(fixed, '\u{2013}', '-')
  fixed = fixed:gsub('\\text' .. TEXT_OPEN .. '(%d+)' .. TEXT_CLOSE, function(n)
    return '\\text' .. texts[tonumber(n)]
  end)
  return fixed
end

local function repair_math(el)
  local fixed = repair_tex(el.text)
  if fixed ~= el.text and kept('equation', el.text) then return nil end
  if fixed ~= el.text then
    report('equation', el.text, fixed)
    el.text = fixed
    return el
  end
end

-- ------------------------------------------------------------------------
-- 2. math typed as text

local RELATIONS = {
  ['='] = '=', ['\u{2260}'] = '\\neq ', ['<'] = '<', ['>'] = '>',
  ['\u{2264}'] = '\\leq ', ['\u{2265}'] = '\\geq ',
  ['\u{2248}'] = '\\approx ', ['\u{223C}'] = '\\sim ', ['~'] = '\\sim ',
}
local OPERATORS = {
  ['+'] = '+', ['\u{2212}'] = '-', ['\u{2013}'] = '-', ['-'] = '-',
  ['\u{00B1}'] = '\\pm ', ['\u{00D7}'] = '\\times ', ['\u{22C5}'] = '\\cdot ',
  ['\u{00B7}'] = '\\cdot ', ['/'] = '/',
}
local PUNCTUATION = {['('] = '(', [')'] = ')', ['['] = '[', [']'] = ']',
                     [','] = ',', [':'] = ':', ['|'] = '|'}

local function is_greek(cp)
  return cp == 0xB5 or (cp >= 0x391 and cp <= 0x3A9)
    or (cp >= 0x3B1 and cp <= 0x3C9) or cp == 0x3D1 or cp == 0x3D5
    or cp == 0x3F5
end

local function is_latin(cp)
  return (cp >= 65 and cp <= 90) or (cp >= 97 and cp <= 122)
end

local function is_letter(cp)
  return is_latin(cp) or is_greek(cp)
    or (cp >= 0xC0 and cp <= 0x24F and cp ~= 0xD7 and cp ~= 0xF7)
    or (cp >= 0x370 and cp <= 0x3FF) or (cp >= 0x400 and cp <= 0x4FF)
end

local function is_digit(cp) return cp >= 48 and cp <= 57 end

local function greek_tex(ch)
  if ch == '\u{00B5}' then return '\u{03BC}' end
  return ch
end

-- A hat or a bar set over a letter, a combining character after it, and
-- the letters that come so composed in one character: math's ŷ and x̄,
-- which a deck's text types as a letter and the mark (OpenStax's
-- statistics decks, the notes of 7 and 13).
local ACCENTS = {[0x302] = '\\hat', [0x304] = '\\bar', [0x305] = '\\bar'}
local COMPOSED = {[0x177] = {'y', '\\hat'}, [0x176] = {'Y', '\\hat'}}

-- A letter alone with a hat or a bar, not part of a word (crêpe's ê
-- stays a word's letter): its TeX, and how many code points it takes.
local function accented_at(cps, i)
  if i > 1 and is_letter(cps[i - 1]) then return nil end
  local cp, letter, accent, n = cps[i], nil, nil, 0
  if COMPOSED[cp] then
    letter, accent, n = COMPOSED[cp][1], COMPOSED[cp][2], 1
  elseif (is_latin(cp) or is_greek(cp)) and cps[i + 1] and ACCENTS[cps[i + 1]] then
    letter, accent, n = utf8.char(cp), ACCENTS[cps[i + 1]], 2
  else
    return nil
  end
  local next_cp = cps[i + n]
  if next_cp and (is_letter(next_cp) or (next_cp >= 0x300 and next_cp <= 0x36F)) then
    return nil
  end
  return accent .. '{' .. greek_tex(letter) .. '}', n
end

-- A Str split into pieces: runs of digits (with a decimal point or comma
-- between digits), runs of letters, a letter with a hat or a bar, and
-- single other characters. A hat or a bar's letter may be followed by a
-- script typed as TeX types one, x̄_n, an underscore or a caret and a
-- letter or a number, which is a piece too.
local function pieces(text)
  local cps = {}
  for _, cp in utf8.codes(text) do cps[#cps + 1] = cp end
  local out, i = {}, 1
  while i <= #cps do
    local cp, j = cps[i], i
    local accented, width = accented_at(cps, i)
    if accented then
      out[#out + 1] = {text = utf8.char(table.unpack(cps, i, i + width - 1)), tex = accented}
      i = i + width
      local mark = cps[i]
      if (mark == 95 or mark == 94) and cps[i + 1] then
        local k = i + 1
        if is_digit(cps[k]) then
          while cps[k + 1] and is_digit(cps[k + 1]) do k = k + 1 end
        elseif not is_latin(cps[k]) then
          k = nil
        end
        if k and not (cps[k + 1] and (is_letter(cps[k + 1]) or is_digit(cps[k + 1]))) then
          local body = utf8.char(table.unpack(cps, i + 1, k))
          out[#out + 1] = {text = utf8.char(table.unpack(cps, i, k)),
                           script = (mark == 95 and '_' or '^') .. '{' .. body .. '}'}
          i = k + 1
        end
      end
      goto continue
    end
    if is_digit(cp) then
      while j + 1 <= #cps and (is_digit(cps[j + 1]) or
            ((cps[j + 1] == 46 or cps[j + 1] == 44) and j + 2 <= #cps
             and is_digit(cps[j + 2]))) do
        j = j + 1
      end
    elseif is_letter(cp) then
      while j + 1 <= #cps and is_letter(cps[j + 1]) do j = j + 1 end
    end
    out[#out + 1] = utf8.char(table.unpack(cps, i, j))
    i = j + 1
    ::continue::
  end
  return out
end

-- How many letters a piece holds, and how many of them are Greek and
-- Latin.
local function letters(s)
  local n, greek, latin = 0, 0, 0
  for _, cp in utf8.codes(s) do
    if is_letter(cp) then n = n + 1 end
    if is_greek(cp) then greek = greek + 1 end
    if is_latin(cp) then latin = latin + 1 end
  end
  return n, greek, latin
end

-- An atom: kind, its TeX, its text, and the inline it stands for.
local function atom(kind, tex, text, el, src)
  return {kind = kind, tex = tex, text = text, el = el,
          src = src or (el and inline_text(el)) or text}
end

local function classify(piece, italic)
  local n, greek, latin = letters(piece)
  local cp = utf8.codepoint(piece, 1)
  if is_digit(cp) then
    return 'num', piece:gsub(',', '{,}')
  end
  if n == 1 and greek == 1 then return 'var', greek_tex(piece) end
  if latin == n and n >= 1 then
    if italic and n == 1 then return 'var', piece end
    if italic and n <= 3 then return 'ivar', piece end
    if n == 1 then return 'letter', piece end
    return 'word', piece
  end
  if n >= 1 then return 'word', piece end
  if piece == '%' then return 'percent', '\\%' end
  if piece == '\u{2032}' then return 'prime', "'" end
  if RELATIONS[piece] then return 'rel', RELATIONS[piece] end
  if OPERATORS[piece] then return 'op', OPERATORS[piece] end
  if PUNCTUATION[piece] then return 'punct', PUNCTUATION[piece] end
  return 'word', piece
end

local atoms_of
local ORDINALS = {st = true, nd = true, rd = true, th = true}

-- The TeX of a sub- or superscript's content, or nil if it holds anything
-- but letters, digits, and the characters above.
local function script_tex(inlines)
  local out = {}
  for _, a in ipairs(atoms_of(inlines, false)) do
    if a.kind == 'word' and not a.text:match('^%a+$') then return nil end
    if a.kind ~= 'sp' then out[#out + 1] = a.tex end
  end
  return table.concat(out)
end

function atoms_of(inlines, italic)
  local out = {}
  for _, el in ipairs(inlines) do
    local t = el.t
    if t == 'Space' or t == 'SoftBreak' then
      out[#out + 1] = atom('sp', ' ', ' ', el)
    elseif t == 'Math' and el.mathtype == 'InlineMath' then
      out[#out + 1] = atom('math', el.text, el.text, el, PLACEHOLDER)
    elseif t == 'Str' then
      local ps = pieces(el.text)
      for _, p in ipairs(ps) do
        local text, kind, tex = p, nil, nil
        if type(p) == 'table' then
          text, kind, tex = p.text, p.script and 'script' or 'var', p.script or p.tex
        else
          kind, tex = classify(p, italic)
        end
        local a = atom(kind, tex, text, #ps == 1 and el or pandoc.Str(text), text)
        a.accent = type(p) == 'table' and not p.script
        out[#out + 1] = a
      end
    elseif t == 'Emph' and #el.content == 1 and el.content[1].t == 'Str'
        and #pieces(el.content[1].text) == 1 then
      local p = pieces(el.content[1].text)[1]
      local kind, tex
      if type(p) == 'table' and not p.script then
        kind, tex = 'var', p.tex
      else
        p = el.content[1].text
        kind, tex = classify(p, true)
        if kind == 'letter' then kind = 'var' end
      end
      local a = atom(kind, tex, el.content[1].text, el)
      a.accent = type(p) == 'table'
      out[#out + 1] = a
    elseif (t == 'Subscript' or t == 'Superscript') then
      local tex = script_tex(el.content)
      -- An ordinal's superscript (the th of nth) is a word's ending.
      local ordinal = t == 'Superscript' and ORDINALS[pandoc.utils.stringify(el)]
      if tex and tex ~= '' and not ordinal then
        local mark = t == 'Subscript' and '_' or '^'
        out[#out + 1] = atom('script', mark .. '{' .. tex .. '}',
                             pandoc.utils.stringify(el), el)
      else
        out[#out + 1] = atom('word', '', pandoc.utils.stringify(el), el)
      end
    else
      out[#out + 1] = atom('word', '', pandoc.utils.stringify(el), el)
    end
  end
  return out
end

-- A base is a single plain letter right before a sub- or superscript, the
-- letter it's set on (n in n sub 1, H in H sub 0): a variable in an
-- expression, but no symbol on its own, so H sub 2 O stays text.
local MATHY = {var = true, ivar = true, fn = true, num = true, rel = true,
               op = true, punct = true, script = true, prime = true,
               sp = true, math = true, percent = true, base = true}
local OPERAND_END = {var = true, ivar = true, num = true, script = true,
                     prime = true, math = true, percent = true, base = true}
local VARIABLE = {var = true, ivar = true, math = true, base = true}

local function join_tex(run)
  local out = ''
  for _, a in ipairs(run) do
    if a.kind ~= 'sp' then
      -- A command's name ends at the first character that isn't an ASCII
      -- letter, as LuaLaTeX reads it; texmath, which makes the MathML,
      -- reads any letter as part of it, so "\times" run into a Greek
      -- letter is "\timesΔT", a command it doesn't know (Chemistry 2e's
      -- q = m × c × ΔT).
      if out:match('\\%a+$') and (a.tex:match('^%a') or a.tex:match('^[\128-\255]')) then
        out = out .. ' '
      end
      out = out .. a.tex
    end
  end
  return (out:gsub('%s+$', ''))
end

local function join_text(run)
  local out = {}
  for _, a in ipairs(run) do out[#out + 1] = a.text end
  return table.concat(out)
end

local function balanced(run)
  local depth = 0
  for _, a in ipairs(run) do
    if a.tex == '(' or a.tex == '[' then depth = depth + 1 end
    if a.tex == ')' or a.tex == ']' then
      depth = depth - 1
      if depth < 0 then return false end
    end
  end
  return depth == 0
end

-- The expression starting at atom i, as (first, last) indexes, or nil.
local function expression_at(atoms, i)
  -- A comma followed by a space ends a run outside parentheses: in
  -- "mu = 5.51, s = 2.15" there are two equations, in N(5.51, 2.15) one.
  -- So does a colon followed by a space in a run with no variable yet, a
  -- label's: in "Plan 1: n sub 1 = 4" the equation is after the colon, in
  -- "H sub 0: mu = 34" the colon is the equation's.
  local j, depth, variable = i, 0, false
  while j <= #atoms and MATHY[atoms[j].kind] do
    local tex = atoms[j].tex
    if tex == '(' or tex == '[' then depth = depth + 1 end
    if tex == ')' or tex == ']' then depth = depth - 1 end
    if (tex == ',' or (tex == ':' and not variable)) and depth <= 0 and atoms[j + 1]
        and atoms[j + 1].kind == 'sp' and j > i then
      break
    end
    if VARIABLE[atoms[j].kind] then variable = true end
    j = j + 1
  end
  local first, last = i, j - 1
  -- Trim what can't begin or end one.
  while first <= last and (atoms[first].kind == 'sp' or
        (atoms[first].kind == 'punct' and atoms[first].tex ~= '(')) do
    first = first + 1
  end
  while last >= first and (atoms[last].kind == 'sp' or
        (atoms[last].kind == 'punct' and atoms[last].tex ~= ')')) do
    last = last - 1
  end
  if first > last then return nil, j end
  local run = {table.unpack(atoms, first, last)}
  if not balanced(run) then return nil, j end
  -- A run that ends in a base's script and runs straight into a letter is
  -- part of a word, a formula's: 2H sub 2 + O sub 2 = 2H sub 2 O.
  local k = last
  while k > first and (atoms[k].kind == 'script' or atoms[k].kind == 'prime') do k = k - 1 end
  local after = atoms[last + 1]
  if k < last and atoms[k].kind == 'base' and after and after.text ~= ''
      and is_letter(utf8.codepoint(after.text, 1)) then
    return nil, j
  end
  -- A run followed straight away by an opening parenthesis or a letter
  -- stopped short of the rest of its formula, whose words it can't take:
  -- F = MS(Factor)/MS(Error) isn't F = MS, then text. A picture's text is
  -- its description, which isn't in the line.
  local next_atom = atoms[last + 1]
  if next_atom and (next_atom.tex == '(' or (next_atom.kind ~= 'sp' and next_atom.text ~= ''
      and not (next_atom.el and next_atom.el.t == 'Image')
      and is_letter(utf8.codepoint(next_atom.text, 1)))) then
    return nil, j
  end
  local has_rel, has_var = false, false
  for _, a in ipairs(run) do
    if a.kind == 'rel' then has_rel = true end
    if VARIABLE[a.kind] then has_var = true end
  end
  local head, tail = run[1], run[#run]
  local starts = OPERAND_END[head.kind] or head.kind == 'fn' or head.tex == '('
  local ends = OPERAND_END[tail.kind] or tail.tex == ')'
  if has_rel and has_var and starts and ends then
    return first, last
  end
  return nil, j
end

-- A lone symbol at atom i: a Greek letter, a letter with a hat or a bar,
-- or an italic letter with a script, standing between words.
local function symbol_at(atoms, i)
  local a = atoms[i]
  if a.kind ~= 'var' then return nil end
  local j = i
  while j + 1 <= #atoms and (atoms[j + 1].kind == 'script' or
        atoms[j + 1].kind == 'prime') do
    j = j + 1
  end
  local greek = select(2, letters(a.text)) == 1
  if not greek and not a.accent and j == i then return nil end
  local before, after = atoms[i - 1], atoms[j + 1]
  local function apart(b)
    return b == nil or b.kind == 'sp' or b.kind == 'punct'
      or (b.kind == 'word' and not b.text:match('^%w'))
  end
  if apart(before) and apart(after) then return i, j end
  return nil
end

local function from_text(inlines)
  local atoms = atoms_of(inlines, false)
  local paragraph, number
  local function located(first, last, tex)
    if not PLACES or PLACES == '' then return end
    if not paragraph then
      local parts = {}
      for _, el in ipairs(inlines) do parts[#parts + 1] = inline_text(el) end
      paragraph = normalize(table.concat(parts))
      paragraph_number = paragraph_number + 1
      number = paragraph_number
    end
    local before, span = {}, {}
    for k = 1, last do
      local target = k < first and before or span
      target[#target + 1] = atoms[k].src
    end
    local text = normalize(table.concat(span))
    local upto = normalize(table.concat(before) .. table.concat(span))
    place(number, paragraph, text, occurrences(upto, text), tex)
  end
  -- A single plain letter right before an opening parenthesis names a
  -- function, and one right before a sub- or superscript is its base.
  for k = 1, #atoms - 1 do
    if atoms[k].kind == 'letter' and atoms[k + 1].tex == '(' then
      atoms[k].kind = 'fn'
    elseif atoms[k].kind == 'letter' and atoms[k + 1].kind == 'script' then
      atoms[k].kind = 'base'
    end
  end
  -- A letter with a hat or a bar is math, as no letter typed as text is
  -- otherwise, so in a run holding one a plain letter or two after an
  -- operator, a relation, or a number's digits, and before an operator, a
  -- relation, or the run's end (punctuation or a word), is a variable
  -- too: ŷ = a + bx and ŷ = 2x + 1, where a plain a + b = c stays text.
  local function plain(a)
    return a.kind == 'letter' or (a.kind == 'word' and a.text:match('^%a%a$') ~= nil)
  end
  local function beside(k, step)
    local j = k + step
    while atoms[j] and atoms[j].kind == 'sp' do j = j + step end
    return atoms[j]
  end
  local function with_accent(k)
    for _, step in ipairs({ -1, 1 }) do
      local j = k + step
      while atoms[j] and (MATHY[atoms[j].kind] or atoms[j].kind == 'letter') do
        if atoms[j].accent then return true end
        j = j + step
      end
    end
    return false
  end
  local variables = {}
  for k, a in ipairs(atoms) do
    local before, after = beside(k, -1), beside(k, 1)
    if plain(a) and before and (before.kind == 'rel' or before.kind == 'op'
                                or (before.kind == 'num' and atoms[k - 1] == before))
        and (after == nil or after.kind == 'rel' or after.kind == 'op'
             or after.kind == 'punct' or (after.kind == 'word' and not plain(after)))
        and with_accent(k) then
      variables[#variables + 1] = a
    end
  end
  for _, a in ipairs(variables) do a.kind = 'var' end
  local out, changed, i = {}, false, 1
  while i <= #atoms do
    local a = atoms[i]
    local first, last
    if MATHY[a.kind] and a.kind ~= 'sp' then
      local stop
      first, stop = expression_at(atoms, i)
      if first then
        last = stop
        -- expression_at returned (first, last)
      end
    end
    if first and kept('expression', join_text({table.unpack(atoms, first, last)})) then
      -- Kept as text, the whole of it: no symbol is made of a part.
      for k = i, last do out[#out + 1] = atoms[k].el end
      i = last + 1
    elseif first then
      local f, l = first, last
      for k = i, f - 1 do out[#out + 1] = atoms[k].el end
      local run = {table.unpack(atoms, f, l)}
      local tex = join_tex(run)
      report('expression', join_text(run), tex)
      located(f, l, tex)
      out[#out + 1] = pandoc.Math('InlineMath', tex)
      changed = true
      i = l + 1
    else
      local s, e = symbol_at(atoms, i)
      if s and kept('symbol', join_text({table.unpack(atoms, s, e)})) then
        for k = i, e do out[#out + 1] = atoms[k].el end
        i = e + 1
      elseif s then
        local run = {table.unpack(atoms, s, e)}
        local tex = join_tex(run)
        report('symbol', join_text(run), tex)
        located(s, e, tex)
        out[#out + 1] = pandoc.Math('InlineMath', tex)
        changed = true
        i = e + 1
      else
        out[#out + 1] = a.el
        i = i + 1
      end
    end
  end
  if changed then
    -- Pieces of one Str that stayed text are joined back together.
    local merged = {}
    for _, el in ipairs(out) do
      local prev = merged[#merged]
      if prev and prev.t == 'Str' and el.t == 'Str' then
        merged[#merged] = pandoc.Str(prev.text .. el.text)
      else
        merged[#merged + 1] = el
      end
    end
    return merged
  end
  return nil
end

local function block_with_inlines(block)
  local fixed = from_text(block.content)
  if fixed then
    block.content = fixed
    return block
  end
end

-- ------------------------------------------------------------------------
-- 3. a minus sign typed as an en dash, in text

-- An en dash written for a minus sign in a page's text, not in an
-- equation: OpenStax's books write a negative number so, –$922.0, and a
-- difference, $1,046 – $1,562, each with an en dash. NVDA doesn't say an
-- en dash at its default punctuation level (some, where symbols.dic puts
-- the en dash at most), and its rule for a negative number says "minus"
-- before a number after a hyphen or a minus sign, not an en dash
-- (source/locale/en/symbols.dic), so the number is heard as positive;
-- and it passes the dash between two numbers on to the synthesizer,
-- which Rob heard read as a range in Principles of Economics 3e's 23.1,
-- 2026-11-06. Made a minus sign, as math.repair_equations makes one
-- inside an equation:
--   - a sign before a number (a digit, or a currency sign or a decimal
--     point and a digit) where a range's dash can't be: at the start of
--     the text or of a sub- or superscript; straight after an opening
--     parenthesis, bracket, or brace, a relation, an operator, a colon, a
--     semicolon, a comma, an opening quotation mark, a currency sign
--     (SIGN_AFTER), or a part's circled letter; or past white space,
--     after a clause's end (a comma, a semicolon, a colon, or a full stop)
--     or after a word with no digit or formula in it, not a unit's
--     (UNIT_START) and not ending in a closing parenthesis or bracket: the
--     slope is –1.5, (–3, –2), 10 to the –4, 75. –66.4 kJ, ⓒ–8, but not
--     24 °C –29 °C, 5′–3′, nor 1990–2000.
--   - a dash between two operands in a run of arithmetic that holds a
--     relation (=, <, >, and the rest), or that "equal to" or "equals"
--     opens: 1 – 0.05 = 0.95, and "is equal to $1,046 – $1,562". A run is
--     the stretches between white spaces made of numbers, a number's
--     degree sign, operators, relations, currency signs, and formulas, a
--     number with the letters it multiplies (48 – 3Q), a quantity's word
--     ($20 billion), or a lone letter (df = n – 1), not a part's label,
--     (b), up to a comma, a semicolon, a colon, or a full stop that ends a
--     clause; a dash at its start takes what it subtracts from in the
--     words before it (the number of cells – 1 = 4), and a sign after a
--     relation or an operator in it is a sign, after a relation past white
--     space too (r = – 0.2752). A range has no relation there (1943 – 2020,
--     $50,000 – $68,999, 13 – 55+), or is of whole numbers, the smaller
--     first, after a relation with nothing after it (n = 2 – 5), and is
--     left as written.
-- Each run of arithmetic a dash is made a minus sign in, or, outside one,
-- the stretch between white spaces it's in, is a row of the report
-- (kind minus, Before and After as text), and the keep sidecar's row for
-- it keeps it as it was. Paragraphs and plain blocks: running text, a
-- list's items, a table's cells, a caption; and a picture's description.
-- Measured before it was written on ten of OpenStax's books
-- (docs/configuration.md, Math).

local MINUS_IN_TEXT = setting('MATH_MINUS_IN_TEXT')
-- Where each such sign is, for writing it into a Word source (format:
-- source): the paragraph's text as the filter reads it, and which of its
-- en dashes, counted from 1.
local MINUS_PLACES = os.getenv('MATH_MINUS_PLACES')
local EN_DASH, MINUS_SIGN, FORMULA = 0x2013, 0x2212, 0xFFFC
local SPACES = {[32] = true, [0xA0] = true, [0x2009] = true, [0x202F] = true}
local CURRENCY = {[36] = true, [0xA3] = true, [0x20AC] = true, [0xA5] = true}
local ENDS_RUN = {[44] = true, [59] = true, [58] = true, [46] = true}  -- , ; : .
local CLOSING = {[41] = true, [93] = true}                              -- ) ]
-- What can close a clause after its comma or full stop: a parenthesis, a
-- bracket, a quotation mark.
local CLOSERS = {[41] = true, [93] = true, [0x201D] = true, [0x2019] = true, [34] = true}
local ARITHMETIC, RELATION = {}, {}
for _, ch in ipairs({'.', ',', '%', '\u{00B0}', '(', ')', '[', ']', '+', '-', '*', '/', '^',
                     '\u{2212}', '\u{2013}', '\u{00D7}', '\u{00B7}', '\u{22C5}',
                     '\u{00F7}', '\u{00B1}', '$', '\u{00A3}', '\u{20AC}', '\u{00A5}'}) do
  ARITHMETIC[utf8.codepoint(ch)] = true
end
for _, ch in ipairs({'=', '<', '>', '\u{2248}', '\u{2260}', '\u{2264}', '\u{2265}'}) do
  ARITHMETIC[utf8.codepoint(ch)] = true
  RELATION[utf8.codepoint(ch)] = true
end

-- A block's text, a character at a time, as inline_text gives it, each
-- from a Str with that Str's number in reading order and its place there,
-- and fresh where it opens a sub- or superscript; a formula is one
-- character, FORMULA.
local function characters(inlines)
  local out, strs = {}, 0
  local function walk(list, fresh)
    for _, el in ipairs(list) do
      local t = el.t
      if t == 'Str' then
        strs = strs + 1
        local k = 0
        for _, cp in utf8.codes(el.text) do
          k = k + 1
          out[#out + 1] = {cp = cp, str = strs, at = k, fresh = fresh}
          fresh = false
        end
      elseif t == 'Space' or t == 'SoftBreak' or t == 'LineBreak' then
        out[#out + 1] = {cp = 32}
        fresh = false
      elseif t == 'Math' then
        out[#out + 1] = {cp = FORMULA, tex = el.text}
        fresh = false
      elseif t == 'Code' then
        for _, cp in utf8.codes(el.text) do out[#out + 1] = {cp = cp} end
        fresh = false
      elseif t == 'Note' or t == 'Image' or t == 'RawInline' then
        -- None of the paragraph's text, as inline_text has it.
      elseif t == 'Superscript' or t == 'Subscript' then
        walk(el.content, true)
        fresh = false
      elseif t == 'Quoted' then
        -- A quotation Pandoc reads as one (a LaTeX source's, an HTML
        -- source's q), its marks the text's, as a Word source has them.
        local double = el.quotetype == 'DoubleQuote'
        out[#out + 1] = {cp = double and 0x201C or 0x2018}
        walk(el.content, false)
        out[#out + 1] = {cp = double and 0x201D or 0x2019}
        fresh = false
      elseif el.content then
        walk(el.content, fresh)
        fresh = false
      end
    end
  end
  walk(inlines, false)
  return out
end

-- The first and last positions of the stretch between white spaces that
-- position i is in.
local function token_at(chars, i)
  local s, e = i, i
  while s > 1 and not SPACES[chars[s - 1].cp] do s = s - 1 end
  while e < #chars and not SPACES[chars[e + 1].cp] do e = e + 1 end
  return s, e
end

-- The words a quantity is written with (OpenStax's $20 billion), and a
-- term, a number and the letters of a variable it multiplies (3Q, 0.5Qd),
-- which a run of arithmetic takes as it takes a number.
local QUANTITY_WORDS = {thousand = true, million = true, billion = true, trillion = true,
                        percent = true}

local function quantity_word(chars, s, e)
  while e >= s and (CLOSERS[chars[e].cp] or ENDS_RUN[chars[e].cp]) do e = e - 1 end
  local word = {}
  for k = s, e do
    if not is_latin(chars[k].cp) then return false end
    word[#word + 1] = utf8.char(chars[k].cp)
  end
  return #word > 0 and QUANTITY_WORDS[table.concat(word):lower()] == true
end

local function term(chars, s, e)
  while s <= e and (chars[s].cp == 40 or chars[s].cp == 91) do s = s + 1 end
  while e >= s and (CLOSERS[chars[e].cp] or ENDS_RUN[chars[e].cp]) do e = e - 1 end
  local k = s
  while k <= e and (is_digit(chars[k].cp) or chars[k].cp == 46 or chars[k].cp == 44) do
    k = k + 1
  end
  if k == s or k > e or not is_digit(chars[k - 1].cp) then return false end
  for j = k, e do
    if not is_letter(chars[j].cp) then return false end
  end
  return true
end

-- Whether the stretch from s to e is one letter, a variable's name, as a
-- book types n or x in its text, a parenthesis or a bracket before it and
-- what closes a clause after it aside ((k – 1.5), q = 1 – p.); but not a
-- letter in parentheses, (b), which labels a part.
local function lone_letter(chars, s, e)
  local opened, closed = false, false
  while s < e and (chars[s].cp == 40 or chars[s].cp == 91) do s, opened = s + 1, true end
  while e > s and (CLOSERS[chars[e].cp] or ENDS_RUN[chars[e].cp]) do
    closed = closed or CLOSING[chars[e].cp] == true
    e = e - 1
  end
  return s == e and is_letter(chars[s].cp) and not (opened and closed)
end

-- Whether the stretch from s to e is a run's: numbers, operators,
-- relations, currency signs, and formulas, or a term, a quantity's word,
-- or a lone letter.
local function arithmetic(chars, s, e)
  for k = s, e do
    local cp = chars[k].cp
    if not (is_digit(cp) or cp == FORMULA or ARITHMETIC[cp]) then
      return term(chars, s, e) or quantity_word(chars, s, e) or lone_letter(chars, s, e)
    end
  end
  return true
end

-- The text from s to e, a formula as its TeX between dollar signs, and
-- each en dash fixed names a minus sign.
local function text_of(chars, s, e, fixed)
  local out = {}
  for k = s, e do
    local c = chars[k]
    if c.tex then
      out[#out + 1] = '$' .. c.tex .. '$'
    else
      out[#out + 1] = utf8.char(fixed and fixed[k] and MINUS_SIGN or c.cp)
    end
  end
  return table.concat(out)
end

-- Whether a number starts at position i: a digit, or a currency sign or a
-- decimal point before one.
local function number_at(chars, i)
  local c = chars[i]
  if not c then return false end
  if is_digit(c.cp) then return true end
  local d, e = chars[i + 1], chars[i + 2]
  if c.cp == 46 then return d ~= nil and is_digit(d.cp) end
  if CURRENCY[c.cp] then
    return d ~= nil and (is_digit(d.cp) or (d.cp == 46 and e ~= nil and is_digit(e.cp)))
  end
  return false
end

-- What a sign can follow with no white space between: an opening
-- parenthesis, bracket, or brace, a relation, an operator, a colon, a
-- semicolon, a comma, an opening quotation mark, or a currency sign.
local SIGN_AFTER = {}
for _, ch in ipairs({'(', '[', '{', '=', '<', '>', '\u{2264}', '\u{2265}', '\u{2248}',
                     '\u{2260}', '+', '\u{00D7}', '\u{00B7}', '\u{22C5}', '/', '\u{00F7}',
                     '*', '^', '\u{00B1}', ':', ';', ',', '\u{201C}', '\u{2018}', '"',
                     '$', '\u{00A3}', '\u{20AC}', '\u{00A5}'}) do
  SIGN_AFTER[utf8.codepoint(ch)] = true
end

-- What a unit set apart from its number starts with: a degree sign, a
-- percent sign, a prime, a double prime.
local UNIT_START = {[0xB0] = true, [37] = true, [0x2032] = true, [0x2033] = true}

-- Whether the en dash at position i is a sign before a number, where a
-- range's dash can't be.
local function sign_at(chars, i)
  if not number_at(chars, i + 1) then return false end
  if chars[i].fresh or i == 1 then return true end
  local cp = chars[i - 1].cp
  -- A part's circled letter too, ⓒ–8, as an answer key gives one.
  if not SPACES[cp] then return SIGN_AFTER[cp] == true or (cp >= 0x24B6 and cp <= 0x24E9) end
  local q = i - 1
  while q >= 1 and SPACES[chars[q].cp] do q = q - 1 end
  if q < 1 then return true end
  -- After a list's comma or a clause's end, a number's sign: (–3, –2).
  if ENDS_RUN[chars[q].cp] then return true end
  local s = token_at(chars, q)
  for k = s, q do
    if is_digit(chars[k].cp) or chars[k].cp == FORMULA then return false end
  end
  -- A unit after a number set apart from it, 24 °C –29 °C, is a range's.
  if UNIT_START[chars[s].cp] then return false end
  return not CLOSING[chars[q].cp]
end

-- Whether the stretch ending at position e ends a clause: a comma, a
-- semicolon, a colon, or a full stop last, or before what closes it.
local function ends_clause(chars, e)
  while e >= 1 and CLOSERS[chars[e].cp] do e = e - 1 end
  return e >= 1 and ENDS_RUN[chars[e].cp] == true
end

-- The run of arithmetic the stretch from s to e is in, its first and last
-- positions, or nil when the stretch holds a word.
local function run_around(chars, s, e)
  if not arithmetic(chars, s, e) then return nil end
  local first, last, k = s, e, s - 1
  while true do
    while k >= 1 and SPACES[chars[k].cp] do k = k - 1 end
    if k < 1 or ends_clause(chars, k) then break end
    local ts = token_at(chars, k)
    if not arithmetic(chars, ts, k) then break end
    first, k = ts, ts - 1
  end
  k = e + 1
  while not ends_clause(chars, last) do
    while k <= #chars and SPACES[chars[k].cp] do k = k + 1 end
    if k > #chars then break end
    local _, te = token_at(chars, k)
    if not arithmetic(chars, k, te) then break end
    last, k = te, te + 1
  end
  return first, last
end

local function relation_in(chars, first, last)
  for k = first, last do
    if RELATION[chars[k].cp] then return true end
  end
  -- "equal to" or "equals" just before the run.
  local words, k = {}, first - 1
  while #words < 2 do
    while k >= 1 and SPACES[chars[k].cp] do k = k - 1 end
    if k < 1 then break end
    local ts = token_at(chars, k)
    table.insert(words, 1, text_of(chars, ts, k):lower())
    k = ts - 1
  end
  return words[#words] == 'equals'
    or (words[#words] == 'to' and words[#words - 1] == 'equal')
end

-- A whole number's value, the stretch from s to e holding its digits alone
-- but what closes a clause after it, or nil.
local function whole_number(chars, s, e)
  while e >= s and (CLOSERS[chars[e].cp] or ENDS_RUN[chars[e].cp]) do e = e - 1 end
  if e < s then return nil end
  local digits = {}
  for k = s, e do
    if not is_digit(chars[k].cp) then return nil end
    digits[#digits + 1] = utf8.char(chars[k].cp)
  end
  return tonumber(table.concat(digits))
end

-- Whether the dash at position i, between the whole numbers from ls to l
-- and from r on, the smaller first, ends its run's arithmetic, a relation
-- before it and none after: a range of values, n = 2 – 5.
local function range_after_relation(chars, i, ls, l, r, last)
  local rs, re = token_at(chars, r)
  if rs ~= r or re > last then return false end
  local a, b = whole_number(chars, ls, l), whole_number(chars, r, re)
  if not (a and b and a < b) then return false end
  for k = i + 1, last do
    if RELATION[chars[k].cp] then return false end
  end
  return true
end

-- Whether the en dash at position i, in the run from first to last, is a
-- minus sign there: between two operands (a number, a formula, what a
-- parenthesis, a percent sign, or a degree sign closes, or a lone
-- letter), white space beside it or not; at the run's start, the words
-- before it what's subtracted from (the number of cells – 1 = 4 – 1 = 3);
-- or before a number, after a relation, an operator, or an opening
-- parenthesis, and past white space after a relation. Not a range of
-- whole numbers that ends the run, after its relation (range_after_relation).
local function in_run(chars, i, first, last)
  local l, r = i - 1, i + 1
  while l >= 1 and SPACES[chars[l].cp] do l = l - 1 end
  while r <= #chars and SPACES[chars[r].cp] do r = r + 1 end
  local right = r <= #chars and chars[r].cp
  local letter_after = false
  if r <= #chars then
    local rs, re = token_at(chars, r)
    letter_after = rs == r and lone_letter(chars, rs, re)
  end
  local operand_after = (r <= last and (number_at(chars, r) or right == FORMULA
                                        or right == 40 or right == 91)) or letter_after
  if l < first then
    if l < 1 then return number_at(chars, i + 1) end
    return operand_after
  end
  local left = chars[l].cp
  local ls = token_at(chars, l)
  if is_digit(left) or left == FORMULA or left == 37 or left == 0xB0 or CLOSING[left]
      or term(chars, ls, l) or quantity_word(chars, ls, l) or lone_letter(chars, ls, l) then
    return operand_after and not range_after_relation(chars, i, ls, l, r, last)
  end
  -- A sign: a relation, an operator, or an opening before it, and after a
  -- relation, a space after it too (r = – 0.2752).
  return (r == i + 1 or RELATION[left] == true) and number_at(chars, r)
end

-- The inlines with each Str whose characters fix names given a minus
-- sign there, in the order characters() numbers them.
local function with_signs(list, fix, counter)
  local out = {}
  for _, el in ipairs(list) do
    local t = el.t
    if t == 'Str' then
      counter.n = counter.n + 1
      local at = fix[counter.n]
      if at then
        local parts, k = {}, 0
        for _, cp in utf8.codes(el.text) do
          k = k + 1
          parts[k] = utf8.char(at[k] and MINUS_SIGN or cp)
        end
        el = pandoc.Str(table.concat(parts))
      end
    elseif t ~= 'Note' and t ~= 'Image' and t ~= 'RawInline' and t ~= 'Code'
        and t ~= 'Math' and el.content then
      el.content = with_signs(el.content, fix, counter)
    end
    out[#out + 1] = el
  end
  return out
end

local minus_places_handle
local minus_paragraph_number = 0

local function minus_place(number, paragraph, occurrence)
  if not MINUS_PLACES or MINUS_PLACES == '' then return end
  if minus_places_handle == nil then
    minus_places_handle = io.open(MINUS_PLACES, 'a') or false
  end
  if minus_places_handle then
    minus_places_handle:write(table.concat({csv(page), csv(number), csv(paragraph),
                                            csv(occurrence), csv('\u{2013}'),
                                            csv('\u{2212}')}, ',') .. '\n')
  end
end

-- The en dashes in inlines to make minus signs, by their positions in
-- characters(inlines), each reported, those the keep sidecar keeps left
-- out; and the characters.
local function signs_in(inlines)
  local chars = characters(inlines)
  local chosen, order = {}, {}
  for i, c in ipairs(chars) do
    if c.cp == EN_DASH and c.str then
      local s, e = token_at(chars, i)
      local first, last = run_around(chars, s, e)
      if first and not relation_in(chars, first, last) then first, last = nil, nil end
      if (first and in_run(chars, i, first, last)) or sign_at(chars, i) then
        -- Reported by the run it's in, or outside one, its stretch.
        local key = first and (first .. ':' .. last) or (s .. ':' .. e)
        if not chosen[key] then
          chosen[key] = {first = first or s, last = last or e, at = {}}
          order[#order + 1] = key
        end
        chosen[key].at[i] = true
      end
    end
  end
  local fixed = {}
  for _, key in ipairs(order) do
    local stretch = chosen[key]
    local before = text_of(chars, stretch.first, stretch.last)
    if not kept('minus', before) then
      report('minus', before, text_of(chars, stretch.first, stretch.last, stretch.at))
      for i in pairs(stretch.at) do fixed[i] = true end
    end
  end
  return fixed, chars
end

-- The inlines with the minus signs signs_in found, or nil for none.
local function signed(inlines, fixed, chars)
  if next(fixed) == nil then return nil end
  local fix = {}
  for i in pairs(fixed) do
    local c = chars[i]
    fix[c.str] = fix[c.str] or {}
    fix[c.str][c.at] = true
  end
  return with_signs(inlines, fix, {n = 0})
end

local function minus_in_text(block)
  local fixed, chars = signs_in(block.content)
  if next(fixed) == nil then return nil end
  if MINUS_PLACES and MINUS_PLACES ~= '' then
    local parts = {}
    for _, el in ipairs(block.content) do parts[#parts + 1] = inline_text(el) end
    minus_paragraph_number = minus_paragraph_number + 1
    local paragraph, n = normalize(table.concat(parts)), 0
    for i, c in ipairs(chars) do
      if c.cp == EN_DASH then
        n = n + 1
        if fixed[i] then minus_place(minus_paragraph_number, paragraph, n) end
      end
    end
  end
  block.content = signed(block.content, fixed, chars)
  return block
end

-- A picture's description, which a screen reader reads as it reads text:
-- the same signs, its own stretch of text. A Word source's copy gets them
-- in the description its picture has there, the image-alt sidecar's or
-- its own, each place a row naming the picture by its file (picture, its
-- path, which en dash of the description).
local function minus_in_description(image)
  local fixed, chars = signs_in(image.caption)
  local content = signed(image.caption, fixed, chars)
  if not content then return nil end
  local n = 0
  for i, c in ipairs(chars) do
    if c.cp == EN_DASH then
      n = n + 1
      if fixed[i] then minus_place('picture', image.src, n) end
    end
  end
  image.caption = content
  return image
end

-- ------------------------------------------------------------------------
-- display style in running text

-- A formula in running text its HTML page sets in display style, which
-- the run marks before Pandoc reads the page, its reader dropping MathML's
-- display style (lib/mathstyle.py: a span of class displaystyle-text): set
-- in display style, \displaystyle opening its TeX, as html-source.lua sets
-- a formula of class displaystyle, where math.display_style_in_text says
-- so, and otherwise in text style, as the reader reads it. The span goes
-- either way, where it holds nothing else of its own. After the repairs,
-- so that a formula's TeX is the same to math-repaired.csv and
-- math-keep.csv whatever the setting: given \displaystyle first, a row
-- copied from a target without the setting kept nothing in one with it.
local DISPLAY_IN_TEXT = (os.getenv('MATH_DISPLAY_STYLE_IN_TEXT') or 'false'):lower() == 'true'
local TEXT_CLASS = 'displaystyle-text'
local DISPLAYED = '^%s*\\displaystyle%f[^%a]'

local function display_in_text(span)
  if not span.classes:includes(TEXT_CLASS) then return nil end
  if DISPLAY_IN_TEXT then
    span.content = span.content:walk({ Math = function(math_)
      if math_.mathtype == 'InlineMath' and not math_.text:match(DISPLAYED) then
        math_.text = '\\displaystyle ' .. math_.text
        return math_
      end
    end })
  end
  span.classes = span.classes:filter(function(name) return name ~= TEXT_CLASS end)
  if span.identifier == '' and #span.classes == 0 and #span.attributes == 0 then
    return span.content
  end
  return span
end

local filters = {}
if REPAIR then
  filters[#filters + 1] = {Math = repair_math}
end
if FROM_TEXT then
  filters[#filters + 1] = {Para = block_with_inlines, Plain = block_with_inlines}
end
if MINUS_IN_TEXT then
  filters[#filters + 1] = {Para = minus_in_text, Plain = minus_in_text,
                           Image = minus_in_description}
end
filters[#filters + 1] = {Span = display_in_text}
return filters
