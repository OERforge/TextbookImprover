-- latex-source.lua -- when a LaTeX source is read: an image's alt text
-- as LaTeX would give it.
--
-- Pandoc's LaTeX reader (3.12, mkImage in Readers/LaTeX.hs) takes the
-- alt key's value as the raw text of its tokens, and an image without
-- one gets the word "image" (PANDOC-NOTES.md, "The LaTeX reader"). So:
--
-- - "image" is taken as no alt text, which the filter then reports as
--   missing. An author who wrote alt={image} meant no more than that.
-- - alt text holding LaTeX (\%, ~, $...$) is read as LaTeX, so 50\%
--   is 50%.
-- - the marker latexsource.py puts in place of the artifact key makes
--   the image decorative, which is what latex-lab makes it.
--
-- And a formula as texmath, which makes its MathML, can read it. texmath
-- (in Pandoc 3.12) stops on a size command in text inside math
-- (\mbox{\tiny noneg}) and on \rule, and the formula is then written
-- as its TeX. A size changes nothing a screen reader says, and a rule of
-- no width is a strut and one of no height a space, so all three go;
-- a rule that shows is left, since only
-- a person can say what it means (latex-conversion-macros.tex can). It
-- stops as well on a text command inside \text, on space inside a text
-- command, on \MakeLowercase and \copyright, and on \hfill, \vspace,
-- and \index (below).
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

local stringify = pandoc.utils.stringify
local ARTIFACT = 'TextbookImproverArtifact'

function Image(img)
  local alt = stringify(img.caption)
  if alt == ARTIFACT then
    img.caption = {}
    img.classes:insert('decorative')
    return img
  end
  if alt == 'image' or alt == '' then
    img.caption = {}
    return img
  end
  if alt:find('[\\$~{}]') then
    local ok, doc = pcall(pandoc.read, alt, 'latex')
    if ok and #doc.blocks == 1 and doc.blocks[1].content then
      img.caption = doc.blocks[1].content
      return img
    end
  end
  return nil
end

local SIZES = { 'tiny', 'scriptsize', 'footnotesize', 'small',
  'normalsize', 'large', 'Large', 'LARGE', 'huge', 'Huge' }

local OLD_FONTS = { bf = 'textbf', it = 'textit', sf = 'textsf',
  tt = 'texttt', rm = 'textrm', sl = 'textsl', em = 'emph' }

-- Text commands texmath reads in a formula, though not inside \text, each
-- as the one it reads.
local TEXT_STYLES = { texttt = 'texttt', textbf = 'textbf', textit = 'textit',
  textrm = 'textrm', textsf = 'textsf', textsl = 'textit', textup = 'textrm',
  textnormal = 'textrm', emph = 'textit' }
local TEXT_COMMANDS = { 'text', 'textrm', 'texttt', 'textit', 'textbf',
  'textsf', 'textsl', 'textup', 'textnormal', 'emph' }

-- \text{rolling a \texttt{1}} as \text{rolling a }\texttt{1}: texmath
-- (Pandoc 3.12) stops on a text command inside \text, and reads each
-- alone. OpenIntro Statistics writes 58 of its formulas so.
local split_text
function split_text(arg)
  local inner = arg:sub(2, -2)
  local pieces, plain, pos = {}, '', 1
  local function flush()
    if plain ~= '' then
      table.insert(pieces, '\\text{' .. plain .. '}')
    end
    plain = ''
  end
  while true do
    local s, e, cmd, group = inner:find('\\(%a+)%s*(%b{})', pos)
    if not s then break end
    plain = plain .. inner:sub(pos, s - 1)
    if TEXT_STYLES[cmd] then
      flush()
      table.insert(pieces, '\\' .. TEXT_STYLES[cmd] .. group)
    elseif cmd == 'underline' then
      flush()
      table.insert(pieces, '\\underline{' .. (split_text(group) or '\\text' .. group) .. '}')
    elseif cmd == 'color' then
      -- The rest of the text in the color, which texmath reads outside it.
      flush()
      local rest = '{' .. inner:sub(e + 1) .. '}'
      table.insert(pieces, '{\\color' .. group .. '{' .. (split_text(rest) or '\\text' .. rest) .. '}}')
      return table.concat(pieces)
    else
      plain = plain .. inner:sub(s, e)
    end
    pos = e + 1
  end
  plain = plain .. inner:sub(pos)
  if #pieces == 0 then
    return nil
  end
  flush()
  return table.concat(pieces)
end

function Math(m)
  local text = m.text
  for _, size in ipairs(SIZES) do
    text = text:gsub('\\' .. size .. '%f[^%a]%s*', '')
  end
  -- A rule of no width is a strut, and one of no height a space, with
  -- or without its optional raise.
  text = text:gsub('\\rule%s*%b[]%s*{%s*0[%a]*%s*}%s*%b{}', '')
  text = text:gsub('\\rule%s*{%s*0[%a]*%s*}%s*%b{}', '')
  text = text:gsub('\\rule%s*%b[]%s*%b{}%s*{%s*0[%a]*%s*}', '\\ ')
  text = text:gsub('\\rule%s*%b{}%s*{%s*0[%a]*%s*}', '\\ ')
  -- A rule no taller than a point and wider than it is tall is a line
  -- to write on, a blank; underlined space says that, and texmath reads it.
  local function blank(width, height)
    local h = tonumber(height)
    if h and h > 0 and h <= 1 then
      return '\\underline{\\hspace{' .. width .. '}}'
    end
    return nil
  end
  text = text:gsub('\\rule%s*%b[]%s*{%s*([%d.]+%a%a)%s*}%s*{%s*([%d.]+)pt%s*}', blank)
  text = text:gsub('\\rule%s*{%s*([%d.]+%a%a)%s*}%s*{%s*([%d.]+)pt%s*}', blank)
  -- A box raised or lowered is the same symbol where texmath is concerned;
  -- \raisebox{1pt}{$\not$} inside an \mbox stops it.
  text = text:gsub('\\raisebox%s*%b{}%s*%b[]%s*%b[]%s*(%b{})', '%1')
  text = text:gsub('\\raisebox%s*%b{}%s*%b[]%s*(%b{})', '%1')
  text = text:gsub('\\raisebox%s*%b{}%s*(%b{})', '%1')
  -- Space inside \mbox is text, which texmath reads as text: an \hspace
  -- there stops it. One at either end goes outside the box, as math
  -- space; one inside is a space.
  text = text:gsub('\\mbox%s*(%b{})', function(arg)
    local inner = arg:sub(2, -2)
    if not inner:find('\\hspace') then return nil end
    local before, after = '', ''
    inner = inner:gsub('^%s*(\\hspace%*?%s*%b{})', function(s) before = s; return '' end)
    inner = inner:gsub('(\\hspace%*?%s*%b{})%s*$', function(s) after = s; return '' end)
    inner = inner:gsub('\\hspace%*?%s*%b{}', ' ')
    return before .. '\\mbox{' .. inner .. '}' .. after
  end)
  -- texmath knows em, pt, in, and cm, not mm; and a length set inside a
  -- formula (\setlength\tabcolsep in an array) lays out nothing a
  -- screen reader says.
  text = text:gsub('(\\hspace%*?%s*{%s*)([%d.]+)%s*mm(%s*})', function(head, n, tail)
    return head .. string.format('%g', tonumber(n) / 10) .. 'cm' .. tail
  end)
  text = text:gsub('\\setlength%s*{?%s*\\%a+%s*}?%s*%b{}', '')
  -- texmath reads \mbox's argument as plain text, so a text command
  -- inside it, \mbox{\textsf R} or \mbox{{\bf c}}, stops it; the
  -- command alone says the same and texmath reads it.
  text = text:gsub('\\mbox%s*{%s*\\(text%a+)%s*(%b{})%s*}', '\\%1%2')
  text = text:gsub('\\mbox%s*{%s*\\(text%a+)%s+([%w])%s*}', '\\%1{%2}')
  for old, new in pairs(OLD_FONTS) do
    text = text:gsub('\\mbox%s*{%s*{%s*\\' .. old .. '%f[^%a]%s*([^{}]*)}%s*}',
      '\\' .. new .. '{%1}')
  end
  -- Space inside a text command's argument stops texmath as inside \mbox:
  -- OpenIntro writes an underscore in a variable's name with a sliver of
  -- space after it, \texttt{income\_\hspace{0.03cm}{}ver}, 34 formulas'
  -- worth. Inside a name it goes; elsewhere it's a space, as \hfill is.
  for _, cmd in ipairs(TEXT_COMMANDS) do
    text = text:gsub('\\' .. cmd .. '%s*(%b{})', function(arg)
      local inner = arg:gsub('\\hspace%*?%s*%b{}%s*{}', '')
      inner = inner:gsub('\\hspace%*?%s*%b{}', ' ')
      inner = inner:gsub('\\hfill%f[^%a]%s*', ' ')
      if inner == arg then return nil end
      return '\\' .. cmd .. inner
    end)
  end
  text = text:gsub('\\text%s*(%b{})', split_text)
  -- \textcolor, which texmath stops on, as \color, which it reads (and
  -- whose color MathML doesn't keep either).
  text = text:gsub('\\textcolor%s*(%b{})%s*(%b{})', '{\\color%1%2}')
  -- Space between a formula's parts, an entry for the index, and space
  -- below it: \hfill as a quad, which texmath reads, and the others gone,
  -- since none is something a screen reader says.
  -- A formula kept in lowercase inside a heading set in capitals
  -- (OpenIntro's boxes: \pmb{\MakeLowercase{t}}) is as it's written;
  -- and \copyright is its sign.
  text = text:gsub('\\MakeLowercase%s*(%b{})', '%1')
  text = text:gsub('\\copyright%f[^%a]%s*', '\\text{\u{A9}}')
  text = text:gsub('\\hfill%f[^%a]', '\\quad')
  text = text:gsub('\\vspace%*?%s*%b{}', '')
  text = text:gsub('\\index%s*%b{}', '')
  -- A group LaTeX's own commands open and close, which texmath stops on
  -- ("unexpected control sequence \\begingroup"), as the braces it reads:
  -- a book's macro a formula uses can hold one, which the copy leaves as
  -- the book wrote it, for LaTeX.
  text = text:gsub('\\begingroup%f[^%a]%s*', '{'):gsub('\\endgroup%f[^%a]', '}')
  text = text:gsub('\\bgroup%f[^%a]%s*', '{'):gsub('\\egroup%f[^%a]', '}')
  -- A strut, height and no width, and a phantom of height alone, which
  -- texmath doesn't know (the calculus notes' \fbox{$\mathstrut$Ex}, 111
  -- times, read as TeX): nothing to see or say, so gone, and a formula
  -- that was nothing else with them; \hphantom is \phantom, whose width it
  -- keeps, and \smash what it holds.
  text = text:gsub('\\mathstrut%f[^%a]%s*', '{}'):gsub('\\strut%f[^%a]%s*', '{}')
  text = text:gsub('\\vphantom%s*%b{}', '{}')
  text = text:gsub('\\hphantom%s*(%b{})', '\\phantom%1')
  text = text:gsub('\\smash%s*%b[]%s*(%b{})', '%1'):gsub('\\smash%s*(%b{})', '%1')
  if text ~= m.text and text:gsub('[%s{}]', '') == '' then
    return {}
  end
  if text ~= m.text then
    -- A line all a removal left, blank, would end LaTeX's paragraph inside
    -- an align* in a PDF ("Paragraph ended before \environment align* was
    -- complete").
    local n
    repeat
      text, n = text:gsub('\n[ \t]*\n', '\n')
    until n == 0
    m.text = text
    return m
  end
  return nil
end

-- A table's header declaration for LaTeX's tagging, which latexsource.py
-- turned into an environment the reader keeps as a div: the pipeline's
-- own declaration, set on the table as a Markdown source's marker sets
-- it (figures-and-tables.lua's data-th-marker), and the div gone.
local DECLARED = { TextbookImproverHeadersFirstRow = 'first-row',
  TextbookImproverHeadersFirstColumn = 'first-column',
  TextbookImproverHeadersBoth = 'both' }

function Div(div)
  -- A box, a tabular of one paragraph column holding prose, which
  -- latexsource.py made an environment of its rows: a div of class box.
  if div.classes[1] == 'TextbookImproverBox' then
    div.classes = { 'box' }
    return div
  end
  -- A table's place in the book's files, which latexsource.py wrapped it
  -- in: kept on the table, for the header pre-pass and a remediated copy.
  local place = div.classes[1] and div.classes[1]:match('^TextbookImproverTable(F%d+N%d+)$')
  if place then
    for _, block in ipairs(div.content) do
      if block.t == 'Table' then
        block.attr.attributes['data-latex-table'] = place
      end
    end
    return div.content
  end
  for _, class in ipairs(div.classes) do
    local declaration = DECLARED[class]
    if declaration then
      for _, block in ipairs(div.content) do
        if block.t == 'Table' then
          block.attr.attributes['data-th-marker'] = declaration
        end
      end
      return div.content
    end
  end
  return nil
end

-- A table with a head and nothing in its body: the reader gives the
-- body one row of empty cells, which no table had (a longtable whose
-- rows are all head, as Pandoc's writer gives a table of one row).
-- The reader gives a longtable's caption to every table in its cells too,
-- its caption state not cleared for them, and a table float's caption and
-- label: an inner table whose caption is its container's has none of its
-- own, nor its container's id, which a reference to the table means (in a
-- PDF from the pages, the inner table is a tabular with no id, and the
-- reference went nowhere: GIAM's rules of inference).
local function clear_inherited(tbl)
  local own = pandoc.utils.stringify(tbl.caption.long)
  if own == '' then return end
  local function clear(cell)
    cell.contents = cell.contents:walk({
      Table = function(inner)
        if pandoc.utils.stringify(inner.caption.long) == own then
          inner.caption = pandoc.Caption()
          if inner.identifier == tbl.identifier then
            inner.identifier = ''
          end
          return inner
        end
      end
    })
  end
  for _, row in ipairs(tbl.head.rows) do
    for _, cell in ipairs(row.cells) do clear(cell) end
  end
  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.body) do
      for _, cell in ipairs(row.cells) do clear(cell) end
    end
  end
end

function Table(tbl)
  clear_inherited(tbl)
  if #tbl.head.rows == 0 or #tbl.bodies ~= 1 then return tbl end
  local body = tbl.bodies[1]
  if #body.head ~= 0 or #body.body ~= 1 then return tbl end
  for _, cell in ipairs(body.body[1].cells) do
    if #cell.contents > 0 then return tbl end
  end
  body.body = {}
  return tbl
end

return { { Image = Image, Math = Math, Div = Div, Table = Table } }
