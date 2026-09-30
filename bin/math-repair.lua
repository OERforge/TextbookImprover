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
--        parenthesis, a function's name (P in P(x < 5)).
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

local page = ''
if PANDOC_STATE and PANDOC_STATE.input_files and PANDOC_STATE.input_files[1] then
  page = PANDOC_STATE.input_files[1]:match('([^/\\]+)$') or ''
  page = page:gsub('%.filtered%.json$', ''):gsub('%.json$', '')
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

-- In order: the bars first, since one of them is an en dash.
local EQUATION_FIXES = {
  {'\\overset{\u{00AF}}{', '\\bar{'},   -- a macron set over a letter
  {'\\overset{\u{2013}}{', '\\bar{'},   -- an en dash set over a letter
  {'\u{00B5}', '\u{03BC}'},             -- micro sign for mu
  {'\u{2206}', '\u{0394}'},             -- increment for capital Delta
  {'\u{0177}', '\\hat{y}'},             -- y-hat, one character
  {'\u{0176}', '\\hat{Y}'},
  {'_{\u{00D8}}', '_{0}'},              -- H sub slashed-O for H sub zero
  {'\u{00B7}', '\\cdot '},              -- middle dot for a product
}

local function repair_tex(tex)
  local fixed = tex
  for _, pair in ipairs(EQUATION_FIXES) do
    fixed = replace_plain(fixed, pair[1], pair[2])
  end
  -- An en dash is a minus, except as text inside \text{...}.
  fixed = fixed:gsub('\\text(%b{})', function(body)
    return '\\text' .. replace_plain(body, '\u{2013}', '\0')
  end)
  fixed = replace_plain(fixed, '\u{2013}', '-')
  fixed = replace_plain(fixed, '\0', '\u{2013}')
  return fixed
end

local function repair_math(el)
  local fixed = repair_tex(el.text)
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

-- A Str split into pieces: runs of digits (with a decimal point or comma
-- between digits), runs of letters, and single other characters.
local function pieces(text)
  local cps = {}
  for _, cp in utf8.codes(text) do cps[#cps + 1] = cp end
  local out, i = {}, 1
  while i <= #cps do
    local cp, j = cps[i], i
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
local function atom(kind, tex, text, el)
  return {kind = kind, tex = tex, text = text, el = el}
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
      out[#out + 1] = atom('math', el.text, el.text, el)
    elseif t == 'Str' then
      local ps = pieces(el.text)
      for _, p in ipairs(ps) do
        local kind, tex = classify(p, italic)
        out[#out + 1] = atom(kind, tex, p,
                             #ps == 1 and el or pandoc.Str(p))
      end
    elseif t == 'Emph' and #el.content == 1 and el.content[1].t == 'Str'
        and #pieces(el.content[1].text) == 1 then
      local p = el.content[1].text
      local kind, tex = classify(p, true)
      if kind == 'letter' then kind = 'var' end
      out[#out + 1] = atom(kind, tex, p, el)
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

local MATHY = {var = true, ivar = true, fn = true, num = true, rel = true,
               op = true, punct = true, script = true, prime = true,
               sp = true, math = true, percent = true}
local OPERAND_END = {var = true, ivar = true, num = true, script = true,
                     prime = true, math = true, percent = true}

local function join_tex(run)
  local out = ''
  for _, a in ipairs(run) do
    if a.kind ~= 'sp' then
      -- a command's name ends at the first non-letter
      if out:match('\\%a+$') and a.tex:match('^%a') then
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
  local j, depth = i, 0
  while j <= #atoms and MATHY[atoms[j].kind] do
    local tex = atoms[j].tex
    if tex == '(' or tex == '[' then depth = depth + 1 end
    if tex == ')' or tex == ']' then depth = depth - 1 end
    if tex == ',' and depth <= 0 and atoms[j + 1] and atoms[j + 1].kind == 'sp'
        and j > i then
      break
    end
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
  local has_rel, has_var = false, false
  for _, a in ipairs(run) do
    if a.kind == 'rel' then has_rel = true end
    if a.kind == 'var' or a.kind == 'ivar' or a.kind == 'math' then
      has_var = true
    end
  end
  local head, tail = run[1], run[#run]
  local starts = OPERAND_END[head.kind] or head.kind == 'fn' or head.tex == '('
  local ends = OPERAND_END[tail.kind] or tail.tex == ')'
  if has_rel and has_var and starts and ends then
    return first, last
  end
  return nil, j
end

-- A lone symbol at atom i: a Greek letter, or an italic letter with a
-- script, standing between words.
local function symbol_at(atoms, i)
  local a = atoms[i]
  if a.kind ~= 'var' then return nil end
  local j = i
  while j + 1 <= #atoms and (atoms[j + 1].kind == 'script' or
        atoms[j + 1].kind == 'prime') do
    j = j + 1
  end
  local greek = select(2, letters(a.text)) == 1
  if not greek and j == i then return nil end
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
  -- A single plain letter right before an opening parenthesis names a
  -- function.
  for k = 1, #atoms - 1 do
    if atoms[k].kind == 'letter' and atoms[k + 1].tex == '(' then
      atoms[k].kind = 'fn'
    end
  end
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
    if first then
      local f, l = first, last
      for k = i, f - 1 do out[#out + 1] = atoms[k].el end
      local run = {table.unpack(atoms, f, l)}
      local tex = join_tex(run)
      report('expression', join_text(run), tex)
      out[#out + 1] = pandoc.Math('InlineMath', tex)
      changed = true
      i = l + 1
    else
      local s, e = symbol_at(atoms, i)
      if s then
        local run = {table.unpack(atoms, s, e)}
        local tex = join_tex(run)
        report('symbol', join_text(run), tex)
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
