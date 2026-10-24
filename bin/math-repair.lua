-- math-repair.lua -- math the source wrote in the wrong characters, or as
-- text. Run at the filter stage after figures-and-tables.lua, so every
-- target gets the repaired page: MathML in HTML and EPUB, LaTeX math in
-- the PDF, an equation in Word, $...$ in Markdown.
--
-- Two things, each with a setting to turn it off:
--
-- 1. Inside an equation (math.repair_equations). Word's equation editor
--    lets an author type a character that looks right and means something
--    else, and the statistics textbook does it hundreds of times: the micro
--    sign for mu, the increment sign for Delta, an en dash for minus (a
--    screen reader says "en dash"), a bar over x written as an en dash or
--    a macron set over it, y-hat as one precomposed character, and a null
--    hypothesis's zero as a slashed O. Each has one right form. The micro
--    sign, y-hat, and the slashed O are also characters no math font in
--    LaTeX maps, so the PDF dropped them.
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

local function repair_tex(tex)
  -- \text{...} is set aside and given only the fixes marked text: its en
  -- dashes are dashes, and its middle dots and y-hats stay characters,
  -- since \text{\cdot} is an error and the equation would be shown as TeX.
  local texts = {}
  local fixed = tex:gsub('\\text(%b{})', function(body)
    for _, pair in ipairs(EQUATION_FIXES) do
      if pair.text then body = replace_plain(body, pair[1], pair[2]) end
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
  -- F = MS(Factor)/MS(Error) isn't F = MS, then text.
  local next_atom = atoms[last + 1]
  if next_atom and (next_atom.tex == '(' or (next_atom.kind ~= 'sp' and next_atom.text ~= ''
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

local filters = {}
if REPAIR then
  filters[#filters + 1] = {Math = repair_math}
end
if FROM_TEXT then
  filters[#filters + 1] = {Para = block_with_inlines, Plain = block_with_inlines}
end
return filters
