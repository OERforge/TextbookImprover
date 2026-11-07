-- math-text.lua -- a formula as text, for a PDF's bookmark, a title, and
-- a picture's alt text: loaded by pdf-target.lua, for a heading's
-- bookmark, deck-pdf.lua, for a slide's, figures-and-tables.lua, for a
-- page's <title>, title-formulas.lua, for the titles made outside the
-- filters, target-blocks.lua, for a picture's alt text, and deck-pptx.lua,
-- for a figure's caption beside it, with dofile, so that all of them write
-- the same text.
--
-- The text is Pandoc's plain writer's, in Unicode where texmath can: x²,
-- α ≤ β, p̂. Where it can't write a formula, it gives the formula's TeX
-- between dollar signs, with a warning that it's rendered as TeX, and so
-- it gave a fraction, a root, and a limit, \underset{x\rightarrow
-- a}{\text{lim}}: 89 of the 554 formulas in titles in OpenStax's public
-- repositories, 50 holding a fraction, 31 a root, 14 a limit, 3 an array,
-- and 1 an arrow over a letter (measured 2026-11-05). All but the arrays
-- are written here first, each in the formula's place as a character of
-- Unicode's private use, which texmath passes as it is, the plain writer
-- writing the rest:
--
--   \frac{a}{b} (\dfrac, \tfrac, \cfrac)  a/b, each in parentheses where
--                                         it's more than one term, as
--                                         (√x − 2)/(x − 4)
--   \sqrt{x}, \sqrt[3]{x}, \sqrt[n]{x}    √x, ∛x, ⁿ√x, the radicand in
--                                         parentheses where it's more
--   \underset{x→a}{\text{lim}}            lim_(x → a), a space after a
--                                         word, a limit's name
--   \overset{\rightarrow}{v}              v⃗, U+20D7; another mark its
--                                         superscript
--   \overline{x}                          x̅, U+0305 on each character
--
-- A fraction is in parentheses where what's beside it would run into it,
-- (1/2)x, a(b/c), ∫(P(x)/Q(x))dx, a mixed number set apart from its whole
-- number, 2 1/3, a root where a letter, a digit, or a parenthesis follows
-- it, (√2)x, and each where a script follows it, (a/b)², (√x)².
--
-- What it still can't write, a matrix, cases, or a command texmath
-- doesn't know, is left as TeX: text() gives nil, and the TeX the plain
-- writer warned of, for the caller to take its warning out of what Pandoc
-- says (build-pdf.py, bookmark_said).
--
-- Then the text is made plain to read: its spaces a word's, a run of them
-- one, as the PDF's text has a formula's run; a script the plain writer
-- puts in parentheses, ℝ^(n), in Unicode's superscripts and subscripts
-- where each of its characters has one, ℝⁿ, x̄ₙ, xⁿ⁺¹, aᵢ, its spaces
-- dropped, and otherwise with its caret or underscore, without the
-- parentheses where it's letters or digits that no letter or digit
-- follows, x^q, with them otherwise, 4^(π), ∫_(C)P dx. In a heading, the
-- caret reaches the heading's structure title too, which LaTeX's tagging
-- makes plain from the bookmark's text, and which latexbuild's PDF_MACROS
-- give a caret, where the tagging made the writer's \^{} a combining
-- circumflex (LATEX-NOTES, Links, bookmarks, and text made plain).
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

local M = {}

-- The first of the private-use characters that stand for what's written
-- here, in the TeX the plain writer is given.
local PLACE = 0xE000

local FRACTIONS = { ['\\frac'] = true, ['\\dfrac'] = true, ['\\tfrac'] = true,
                    ['\\cfrac'] = true }
local ARROWS = { ['\\rightarrow'] = true, ['\\to'] = true, ['\\longrightarrow'] = true }

-- Unicode's superscripts and subscripts, a script's character on the
-- left: the digits, signs, and parentheses of its block of them, the
-- Latin letters it and its modifier letters have, a few Greek ones, and a
-- degree for a superscript ring, as texmath writes ^\circ (∘). A script
-- that holds one already, a script within a script, has none, so that
-- x^{2^{3}} is x^(2³), as the plain writer writes it, and not x²³.
local SCRIPTS = [[
0 ⁰ ₀|1 ¹ ₁|2 ² ₂|3 ³ ₃|4 ⁴ ₄|5 ⁵ ₅|6 ⁶ ₆|7 ⁷ ₇|8 ⁸ ₈|9 ⁹ ₉|+ ⁺ ₊|− ⁻ ₋|- ⁻ ₋|= ⁼ ₌|( ⁽ ₍|) ⁾ ₎|
a ᵃ ₐ|b ᵇ .|c ᶜ .|d ᵈ .|e ᵉ ₑ|f ᶠ .|g ᵍ .|h ʰ ₕ|i ⁱ ᵢ|j ʲ ⱼ|k ᵏ ₖ|l ˡ ₗ|m ᵐ ₘ|n ⁿ ₙ|o ᵒ ₒ|
p ᵖ ₚ|r ʳ ᵣ|s ˢ ₛ|t ᵗ ₜ|u ᵘ ᵤ|v ᵛ ᵥ|w ʷ .|x ˣ ₓ|y ʸ .|z ᶻ .|A ᴬ .|B ᴮ .|D ᴰ .|E ᴱ .|G ᴳ .|
H ᴴ .|I ᴵ .|J ᴶ .|K ᴷ .|L ᴸ .|M ᴹ .|N ᴺ .|O ᴼ .|P ᴾ .|R ᴿ .|T ᵀ .|U ᵁ .|V ⱽ .|W ᵂ .|α ᵅ .|
β ᵝ ᵦ|γ ᵞ ᵧ|δ ᵟ .|ε ᵋ .|θ ᶿ .|ι ᶥ .|ρ . ᵨ|φ ᵠ ᵩ|χ ᵡ ᵪ|∘ ° .|° ° .]]
local SUPERSCRIPTS, SUBSCRIPTS, SCRIPTED = {}, {}, {}
for plain, sup, sub in SCRIPTS:gmatch('([^%s|]+) ([^%s|]+) ([^%s|]+)') do
  if sup ~= '.' then SUPERSCRIPTS[plain], SCRIPTED[sup] = sup, true end
  if sub ~= '.' then SUBSCRIPTS[plain], SCRIPTED[sub] = sub, true end
end

local CHAR = '[%z\1-\127\194-\244][\128-\191]*'

-- What may stand before a fraction, and after it, with no parentheses
-- around it: the formula's start or end, a space, an operator or a
-- relation, a big operator before it, punctuation after it, and what opens
-- a group before it and closes one after it.
local BEFORE, AFTER = { [''] = true }, { [''] = true }
for char in ('( [ { | , ; : = < > + − - ± ∓ ⋅ · × ÷ ≤ ≥ ≠ ≈ → ∫ ∬ ∭ ∮ ∑ ∏'):gmatch('%S+') do
  BEFORE[char] = true
end
for char in (') ] } | , . ; : ! ? = < > + − - ± ∓ ⋅ · × ÷ ≤ ≥ ≠ ≈ →'):gmatch('%S+') do
  AFTER[char] = true
end

-- Whether a character is a space, as texmath writes one.
local function spaced(char)
  return char:match('^%s$') or char:match('^\226\128[\128-\138]$') or char == '\194\160'
end

-- A script's text in the scripts' characters of the map, its spaces
-- dropped, or nil where a character has none.
local function scripted(text, map)
  local out = {}
  for char in text:gsub('%s', ''):gmatch(CHAR) do
    if not map[char] then return nil end
    out[#out + 1] = map[char]
  end
  return #out > 0 and table.concat(out) or nil
end

-- The text made plain to read: its spaces a word's, a script in
-- parentheses in the scripts' characters where each of its characters
-- has one, its spaces dropped, or without its parentheses where it's
-- letters or digits of ASCII that no letter or digit follows, the
-- innermost first and then the one it's in, so that a degree in a
-- superscript, ^(^(∘)), as texmath writes ^{{^\circ}}, is °; and a run of
-- spaces one.
local function tidy(text)
  text = text:gsub('\226\128[\128-\138]', ' '):gsub('\194\160', ' ')
  for _ = 1, 3 do
    local whole = text
    text = whole:gsub('([_^])(%([^()]*%))()', function(mark, group, after)
      local inner = group:sub(2, -2)
      local mapped = scripted(inner, mark == '^' and SUPERSCRIPTS or SUBSCRIPTS)
      if mapped then return mapped end
      if inner:match('^%w+$') and not whole:sub(after, after):match('%w') then
        return mark .. inner
      end
      return nil
    end)
    if text == whole then break end
  end
  return (text:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', ''))
end

-- Whether a text is one term: no space and no slash outside parentheses
-- that hold the whole of it.
local function atom(text)
  if not text:find('[%s/]') then return true end
  if text:sub(1, 1) == '(' and text:sub(-1) == ')' then
    local depth = 0
    for at = 1, #text do
      local char = text:sub(at, at)
      if char == '(' then depth = depth + 1 elseif char == ')' then depth = depth - 1 end
      if depth == 0 and at < #text then return false end
    end
    return true
  end
  return false
end

-- A text as one term: as it is where it's one already, a root, say, or
-- where atom finds it one; in parentheses otherwise.
local function term(text, one)
  return (one or atom(text)) and text or '(' .. text .. ')'
end

-- One argument at i, its spaces skipped: a group's contents, a control
-- sequence, or a character; and where it ends. nil where there's none.
local function argument(tex, i)
  i = tex:find('[^ \t\n]', i) or #tex + 1
  local c = tex:sub(i, i)
  if c == '' or c == '}' then return nil, i end
  if c == '{' then
    local depth, at = 0, i
    while at <= #tex do
      local char = tex:sub(at, at)
      if char == '\\' then
        at = at + 2
      else
        if char == '{' then
          depth = depth + 1
        elseif char == '}' then
          depth = depth - 1
          if depth == 0 then return tex:sub(i + 1, at - 1), at + 1 end
        end
        at = at + 1
      end
    end
    return nil, i
  end
  if c == '\\' then
    local name = tex:match('^\\%a+', i) or tex:sub(i, i + 1)
    return name, i + #name
  end
  local char = tex:match('^' .. CHAR, i)
  return char, i + #char
end

-- An optional argument at i, [ ... ], its spaces skipped, and where it
-- ends; nil and i where there's none.
local function optional(tex, i)
  local at = tex:find('[^ \t\n]', i) or #tex + 1
  if tex:sub(at, at) ~= '[' then return nil, i end
  local close = tex:find(']', at, true)
  if not close then return nil, i end
  return tex:sub(at + 1, close - 1), close + 1
end

local convert

-- The text of each construct the plain writer can't write, at i in tex,
-- where the control sequence name begins, where it ends, and whether it's
-- one term, as a root is and a fraction isn't; nil where it can't be
-- written.
local function construct(name, tex, i, warned)
  local at = i + #name
  if FRACTIONS[name] then
    local a, b, a_term, b_term, ta, tb
    a, at = argument(tex, at)
    b, at = argument(tex, at)
    if a then ta, a_term = convert(a, warned) end
    if b then tb, b_term = convert(b, warned) end
    if not (ta and tb) then return nil end
    return term(ta, a_term) .. '/' .. term(tb, b_term), at, false
  elseif name == '\\sqrt' then
    local n, a, ta, tn, a_term
    n, at = optional(tex, at)
    a, at = argument(tex, at)
    if a then ta, a_term = convert(a, warned) end
    if n then tn = convert(n, warned) end
    if not ta or (n and not tn) then return nil end
    local sign = '√'
    if tn == '3' then sign = '∛'
    elseif tn == '4' then sign = '∜'
    elseif tn and tn ~= '2' then sign = (scripted(tn, SUPERSCRIPTS) or tn) .. '√' end
    return sign .. term(ta, a_term), at, true
  elseif name == '\\underset' then
    local b, a
    b, at = argument(tex, at)
    a, at = argument(tex, at)
    local tb, ta = b and convert(b, warned), a and convert(a, warned)
    if not (ta and tb) then return nil end
    return ta .. '_(' .. tb .. ')' .. (ta:match('^[%a\128-\255]+$') and ' ' or ''), at, false
  elseif name == '\\overset' then
    local b, a
    b, at = argument(tex, at)
    a, at = argument(tex, at)
    local ta = a and convert(a, warned)
    if not (ta and b) then return nil end
    if ARROWS[b] then return ta .. '\u{20D7}', at, atom(ta) end
    local tb = convert(b, warned)
    if not tb then return nil end
    return ta .. '^(' .. tb .. ')', at, atom(ta)
  elseif name == '\\overline' then
    local a
    a, at = argument(tex, at)
    local ta = a and convert(a, warned)
    if not ta then return nil end
    return (ta:gsub('[^%s()]' .. '[\128-\191]*', '%0\u{0305}')), at, atom(ta)
  end
end

local CONSTRUCTS = { ['\\sqrt'] = true, ['\\underset'] = true, ['\\overset'] = true,
                     ['\\overline'] = true }

-- A formula's TeX as text, and whether it's one term, a root alone, say;
-- or nil where the plain writer can't write a part of it, the TeX it
-- warned of added to warned.
convert = function(tex, warned)
  local parts, bare, kinds, out, i, one = {}, {}, {}, {}, 1, false
  while i <= #tex do
    local name = tex:match('^\\%a+', i)
    if name and (FRACTIONS[name] or CONSTRUCTS[name]) then
      local text, after, is_term = construct(name, tex, i, warned)
      if not text then return nil end
      parts[#parts + 1] = text
      bare[#parts] = not (FRACTIONS[name] or name == '\\sqrt') and atom(text)
      kinds[#parts] = FRACTIONS[name] and 'fraction' or name == '\\sqrt' and 'root' or nil
      out[#out + 1] = utf8.char(PLACE + #parts)
      i, one = after, is_term
    else
      local token = name or tex:match('^\\.', i) or tex:match('^' .. CHAR, i) or tex:sub(i, i)
      out[#out + 1] = token
      i = i + #token
    end
  end
  local written = table.concat(out):match('^%s*(.-)%s*$')
  if written == '' then return '' end
  -- One term, where the formula is a single construct that is one.
  one = one and #parts == 1 and written == utf8.char(PLACE + 1)
  local doc = pandoc.Pandoc({ pandoc.Plain({ pandoc.Math('InlineMath', written) }) })
  local text = pandoc.write(doc, 'plain', { wrap_text = 'none' }):gsub('%s+$', '')
  if text == '$' .. written .. '$' then
    table.insert(warned, written)
    return nil
  end
  -- Each part in its place, in parentheses where a script follows it and
  -- it's a fraction, a root, or more than one term, (a/b)², (√x)², as
  -- texmath writes the script of a group; a fraction where anything but a
  -- space, an operator, a relation, or what opens or closes the formula or
  -- a group is beside it, (1/2)x, a(b/c), (a/b)(c/d), ∫(P(x)/Q(x))dx, but
  -- a mixed number apart from its whole number, 2 1/3; and a root a letter,
  -- a digit, or a parenthesis follows, (√2)x.
  text = text:gsub('()(\238[\128-\191][\128-\191])()', function(at, char, after)
    local k = utf8.codepoint(char) - PLACE
    if not parts[k] then return nil end
    local part = parts[k]
    local following = text:match('^' .. CHAR, after) or ''
    local preceding = text:sub(1, at - 1):match('(' .. CHAR .. ')$') or ''
    -- A part before it as it's written, its last character, a limit's
    -- space after its name; a part after it is never one a fraction may
    -- run into.
    local last_part = parts[(preceding:match('^\238') and utf8.codepoint(preceding) or 0) - PLACE]
    if last_part then preceding = last_part:match('(' .. CHAR .. ')$') or '' end
    if (following == '^' or following == '_' or SCRIPTED[following]) and not bare[k] then
      return '(' .. part .. ')'
    end
    if kinds[k] == 'fraction' then
      if preceding:match('^%d$') and part:match('^%d+/%d+$') and not following:match('^[%w(]') then
        return ' ' .. part
      end
      if not (BEFORE[preceding] or spaced(preceding)) or not (AFTER[following] or spaced(following)) then
        return '(' .. part .. ')'
      end
    elseif kinds[k] == 'root' and following:match('^[%w(]') then
      return '(' .. part .. ')'
    end
    return part
  end)
  return tidy(text), one
end

-- An inline formula's text, or nil and the TeX the plain writer warned of
-- where it's left as TeX.
function M.text(math_)
  local warned = {}
  local text = convert(math_.text:match('^%s*(.-)%s*$'), warned)
  return text or nil, warned
end

-- A formula's text in a title, a page's <title>, a piece's, an EPUB
-- chapter's, its entry in the contents, and a cartridge's name for it,
-- which hold no MathML, and where Pandoc's writers give a formula as its
-- TeX: (text, false), or, for one text() can't write, a matrix, (its TeX
-- between dollar signs, true), as the plain writer gives it. The plain
-- writer's warning that such a formula is rendered as TeX is silenced
-- (pandoc.log.silence, Pandoc 3.2 on), since on the page it isn't: the run
-- says once which formulas are their TeX in titles (title-formulas.lua).
function M.title_text(math_)
  local _, text = pandoc.log.silence(M.text, math_)
  if text then return text, false end
  local fence = math_.mathtype == 'DisplayMath' and '$$' or '$'
  return fence .. math_.text .. fence, true
end

-- Inlines or blocks with each formula as its text in a title
-- (title_text): a picture's description, which the writers make text for
-- its alt text, as they make a title text, a formula its TeX
-- (target-blocks.lua), and a figure's caption compared with it
-- (target-blocks.lua, deck-pptx.lua). A formula it can't write is its TeX
-- between dollar signs there too.
function M.texted(content)
  local walker = {
    Math = function(math_) return pandoc.Str((M.title_text(math_))) end,
  }
  if pandoc.utils.type(content) == 'Blocks' then return content:walk(walker) end
  return pandoc.Inlines(content):walk(walker)
end

return M
