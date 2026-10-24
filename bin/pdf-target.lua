-- pdf-target.lua -- what Pandoc's LaTeX writer can't be told, for a
-- tagged PDF. Run by build-pdf.py on the assembled book, after
-- target-blocks.lua; the header it relies on (\OERLinkContents, the
-- artifact key) is written by build-pdf.py too.
--
-- Four things, each because the writer has no way to express it
-- (read in Pandoc 3.11's Writers/LaTeX.hs and Writers/LaTeX/Table.hs):
--
-- 1. Row headers. The writer folds a body's row-head cells into its
--    ordinary cells, so a table the header pre-pass declared with a
--    header column comes out with none. latex-lab's table code takes
--    the columns from \tagpdfsetup{table/header-columns=...}, set
--    before the table and cleared after it, where there's tagging (an
--    untagged PDF has no \tagpdfsetup). Header rows need nothing:
--    the writer puts the head in longtable's \endfirsthead and \endhead,
--    and latex-lab tags those rows TH.
--
-- 2. Decorative images. The writer passes an image's alt attribute, or
--    else its description, as the alt key, and latex-lab gives an image
--    whose alt is empty its file name instead (the alt-text-missing
--    warning in latex-lab-testphase-graphic.sty), so an image the filter
--    marked decorative (alt="", aria-hidden) would be a figure described
--    by its file name. latex-lab's artifact key marks it as an artifact. The image stays an Image in the AST, so
--    Pandoc still copies it where LaTeX runs; only the key is set around
--    it, in a group.
--
-- 3. A link's /Contents. Every link annotation gets one: the link's
--    visible text, followed by its description when it has one (its
--    title, or an aria-label from an older source). The visible text
--    comes first because WCAG 2.5.3 wants the accessible name to hold
--    what is seen; LaTeX's own default is the address, or "Go to
--    destination" and an id, which is what Acrobat would read out.
--    hyperref's \pdfstringdef, which writes it, reads -- and --- as
--    dashes and ?` and !` as inverted marks, as TeX's text does, so an
--    empty group ({}) after each hyphen and before each backtick keeps
--    the text's own: an address's lang--en isn't lang–en.
--
-- 4. A table inside a table's cell. The writer makes each a longtable,
--    and LaTeX stops on a longtable inside another ("Extra alignment tab";
--    jgm/pandoc#3586). The inner table is written as a tabular, its head
--    declared for tagging, or, where a cell spans rows, as its rows, one
--    line each, its cells' text side by side: GIAM's long division, a
--    layout, is the case this was first measured on.
--
-- 5. An eqnarray* formula, which the writer wraps in \[ \] where it writes
--    an eqnarray as it is, and LaTeX stops on: written as it is. And \pmb,
--    on which LuaTeX stopped while the formula was tagged.
--
-- 6. A heading's label and links (below).
--
-- 7. A footnote in a definition list's term, which the writer gives as a
--    mark in the term and its text after the list (\footnotemark,
--    \footnotetext), and LaTeX's tagging stops on that pair in a list's
--    label (the number of automatic begin and end text-unit hooks differ,
--    LaTeX 2026-06-01). It goes at the head of the term's definition, where
--    the writer gives it as a footnote, as it does in a paragraph.
--
-- 8. A passage in another language, a span, a link, or a div with a lang
--    attribute, which the writer marks for babel, whose commands set its
--    hyphenation and tag nothing: the PDF had /Lang in its catalog alone,
--    where PDF/UA-1 wants every change of language declared (ISO 14289-1,
--    7.2). A span or a link is tagged a Span with its language
--    (latexbuild's \oerlang), and a div's blocks are each in an
--    oerlanguage environment, whose structure elements take it, as a
--    deck's PDF tags them (deck-pdf.lua); babel's command is kept inside.
--    A div holding a heading has the blocks between its headings so
--    marked, the heading's words in \oerlang, so no section's element,
--    which goes on past the div's end, takes the language.
--
-- 9. A caption that carries its own label, "Figure 1.1 The real number
--    line", as a book whose captions number themselves has (OpenStax's),
--    which LaTeX numbered again: "Figure 1: Figure 1.1 The real number
--    line". And a figure the book marks unnumbered (class unnumbered, as
--    OpenStax marks a chapter's opening picture), which LaTeX numbered:
--    "Figure 1: Credit: …". Such a figure or table is set in a group with
--    \OERNoCaptionLabel (latexbuild's PDF_MACROS), and its caption gets no
--    label of LaTeX's, as an unnumbered table's has none. A caption's own
--    label is one of the words the captions.figure_prefixes or
--    captions.table_prefixes setting names, on a word boundary, then a
--    number. One in a table's cell, which LaTeX doesn't number, is left.
--
-- 10. A formula with an alignment in it (a matrix, an array, cases) in a
--    table's cell or caption, set in braces (below).
--
-- 11. A footnote in a figure's caption, whose mark took a number for each
--    time LaTeX set the caption, so a tagged PDF's skipped one (below).
--
-- 12. A footnote in a table inside a table's cell (4), which was a
--    minipage's (below).
--
-- 13. A layout table (figures-and-tables.lua's role="presentation"), which
--    LaTeX's tagging made a Table: tagged a division of paragraphs, a
--    row's cells in turn, its caption a paragraph before it (below).
--
-- 14. A table's id with no caption to hold it, which the writer put in an
--    empty caption that LaTeX numbered, or, for a table of class
--    unnumbered, nowhere: an anchor before the table (below).
--
-- 15. A table wider than a line whose columns have no widths and whose
--    cells are each a paragraph, which the writer set in columns that
--    don't wrap: given widths (below).
--
-- 16. A heading inside a list, a quotation, a table, a figure, or a
--    footnote, which the writer makes a sectioning command there, and
--    LaTeX's tagging couldn't close the section it opened: a paragraph
--    tagged as a heading (below).
--
-- 17. An image with a width or a height, which the writer set at that
--    size, wider than its line or not: scaled to fit, as one with
--    neither is (below).
--
-- 18. A fill-in blank, a run of four or more underscores, which TeX can't
--    break, so a line ending in one ran into the margin: marked, for
--    latexbuild's PDF_MACROS to draw shorter where it runs past its line,
--    and to tag as a Span whose ActualText is "blank", which a screen
--    reader says in place of the underscores (below).
--
-- 19. A table, or a formula that TeX can't break, too wide for its line,
--    which ran into the margin or past the paper's edge: numbered, for
--    latexbuild's FIT_MACROS to measure as LaTeX sets it and fit to its
--    line on a later run (below).
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


-- Characters LaTeX would read as markup, in text handed to a macro
-- argument. \pdfstringdef turns the escaped forms back into characters.
local SPECIALS = {
  ["\\"] = "\\textbackslash{}", ["{"] = "\\{", ["}"] = "\\}",
  ["#"] = "\\#", ["$"] = "\\$", ["%"] = "\\%", ["&"] = "\\&",
  ["_"] = "\\_", ["~"] = "\\textasciitilde{}",
  ["^"] = "\\textasciicircum{}",
}

local function tex_escape(s)
  return (s:gsub("[\\{}#%$%%&_~%^]", SPECIALS))
end

local function squash(s)
  return (s:gsub("%s+", " "):gsub("^ ", ""):gsub(" $", ""))
end

-- A link's /Contents as \pdfstringdef should keep it, its hyphens and
-- backticks apart from what's beside them (3).
local function unjoined(s)
  return (s:gsub("%-", "-{}"):gsub("`", "{}`"))
end

-- The words that begin a caption's own label (9), from the captions.*
-- settings build-pdf.py passes on, lowercased.
local function label_words(name, fallback)
  local list = {}
  for word in (os.getenv(name) or fallback):gmatch('[^,]+') do
    word = word:match('^%s*(.-)%s*$')
    if word ~= '' then list[#list + 1] = word:lower() end
  end
  return list
end

local FIGURE_WORDS = label_words('FIGURE_LABEL_PREFIXES', 'Figure')
local TABLE_WORDS = label_words('TABLE_LABEL_PREFIXES', 'Table')

-- Whether a caption opens with its own label (9): one of the words, then
-- a space or a no-break space, then a number ("Figure 1.1", "Table A.2:").
-- "Tables 1 and 2" doesn't, its word running on.
local function own_label(caption, words)
  local blocks = caption and caption.long or {}
  if #blocks == 0 then return false end
  local text = stringify(blocks[1]):gsub('\194\160', ' '):gsub('^%s+', '')
  local lower = text:lower()
  for _, word in ipairs(words) do
    if lower:sub(1, #word) == word then
      local number = text:sub(#word + 1):match('^%s+(%S+)')
      if number and number:find('%d') then return true end
    end
  end
  return false
end

-- A figure the book marks unnumbered (9): the class on the figure, as an
-- HTML page gives it, or on its one image, where the Markdown reader puts
-- an implicit figure's attributes.
local function unnumbered(fig)
  if fig.classes:includes('unnumbered') then return true end
  local only = #fig.content == 1 and fig.content[1]
  if only and (only.t == 'Plain' or only.t == 'Para') and #only.content == 1
      and only.content[1].t == 'Image' then
    return only.content[1].classes:includes('unnumbered')
  end
  return false
end

-- A figure or a table in a table's cell is no float: the writer sets such
-- a figure in a center environment, its caption a paragraph LaTeX doesn't
-- number, so a caption's own label needs nothing done there, and
-- \OERNoCaptionLabel stopped LaTeX ("Misplaced \noalign": in a longtable's
-- cell, \captionsetup is the caption package's form for a caption between
-- rows), on two figures a LibreTexts page sets side by side in a table.
-- Each is marked in a pass before Figure's and Table's.
local IN_CELL = 'oer-in-cell'

local function mark_in_cells(tbl)
  return tbl:walk({
    Figure = function(fig) fig.attributes[IN_CELL] = '1'; return fig end,
    Table = function(inner) inner.attributes[IN_CELL] = '1'; return inner end,
  })
end

local function in_cell(element)
  local marked = element.attributes[IN_CELL] ~= nil
  element.attributes[IN_CELL] = nil
  return marked
end

-- A figure's or a table's blocks in a group with \OERNoCaptionLabel,
-- which holds to the group's end.
local function without_label(blocks)
  local out = pandoc.Blocks{ pandoc.RawBlock('latex', '{\\OERNoCaptionLabel') }
  out:extend(blocks)
  out:insert(pandoc.RawBlock('latex', '}'))
  return out
end

-- A quotation inside a table cell is unwrapped to what it holds: a PDF's
-- structure doesn't allow a BlockQuote in a TD (ISO/TS 32005, which veraPDF
-- reports as TD-BlockQuote). DCIC sets code side by side in a table that
-- way, five blocks of it, indented as quotations.
local unquote = {BlockQuote = function(quote) return quote.content end}

-- LaTeX's tagging told something, where there is tagging: an untagged
-- PDF (pdf.standard: []) has no \tagpdfsetup, and LaTeX stopped on one.
local function tagging_setup(keys)
  return '\\ifdefined\\tagpdfsetup\\tagpdfsetup{' .. keys .. '}\\fi'
end

-- A layout table, which only lines things up: figures-and-tables.lua
-- writes one with role="presentation", whatever said it was one. Tagged a
-- division of paragraphs, a row's cells in turn, not a table, by
-- latex-lab-testphase-table's table/tagging=div, as the LaTeX source copy
-- tags a box (texremediate.BOX_OPEN), the setting kept to the table by a
-- group. Its other layout setting, table/tagging=presentation, keeps
-- Table, TR, and TD and adds the ARIA role presentation, which a reader may
-- not honor, and PDF/UA-2 says a role shall not contradict its structure
-- element's meaning (ISO 14289-2, 8.2.6.4), which a Table "presentation"
-- arguably does. A data table inside a layout table is set back to a
-- table: tagging on, and the two plugs div leaves set to a layout table's
-- set to a table's again (texremediate.DATA_OPEN).
local LAYOUT_ROLES = { presentation = true, none = true }
local LAYOUT_OPEN = '{' .. tagging_setup('table/tagging=div')
local TABLE_PLUGS = '\\AssignTaggingSocketPlug{tbl/hmode/begin}{Table}'
  .. '\\AssignTaggingSocketPlug{tbl/vmode/begin}{Table}'

local function is_layout(tbl)
  return LAYOUT_ROLES[tbl.attr.attributes.role] ~= nil
end

-- A cell spanning rows is set with \multirow, which LaTeX's tagging code
-- doesn't follow (the tagging project lists multirow as incompatible): it
-- tags the cell as one row's and the rows below as having an empty cell
-- of their own there. table/multirow, said inside the cell, gives it its
-- RowSpan and leaves the cells it covers untagged.
local function mark_row_span(cell)
  if (cell.row_span or 1) <= 1 then return end
  local raw = pandoc.RawInline('latex',
    tagging_setup(string.format('table/multirow=%d', cell.row_span)) .. ' ')
  local first = cell.contents[1]
  if first and (first.t == 'Plain' or first.t == 'Para') then
    first.content:insert(1, raw)
  else
    cell.contents:insert(1, pandoc.Plain({raw}))
  end
end

-- A formula with an alignment in it, in a table's cell or caption: its &
-- in braces. LaTeX's tagging reads a formula whole, as a macro's argument,
-- before setting it, and TeX takes an & it reads at the table's own level,
-- in an argument too, as the end of the cell; LaTeX stopped ("Forbidden
-- control sequence found while scanning use of
-- \__math_grab_inline_delim:w"). OpenStax's dev-math books check a
-- solution so in their worked examples' steps, an array of its equations
-- inline in a cell; a caption stopped LaTeX the same way, in nameref's
-- reading of its title. In braces, the & aren't the table's.
local braced_math = {Math = function(math)
  if math.text:find('&', 1, true) then
    return {pandoc.RawInline('latex', '{'), math, pandoc.RawInline('latex', '}')}
  end
end}

local function unquote_cells(rows)
  for _, row in ipairs(rows) do
    for _, cell in ipairs(row.cells) do
      cell.contents = pandoc.Blocks(cell.contents):walk(unquote)
      mark_row_span(cell)
    end
  end
end

local nested_seen = false

local function rows_of(tbl)
  local rows = {}
  for _, row in ipairs(tbl.head.rows) do rows[#rows + 1] = row end
  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.head) do rows[#rows + 1] = row end
    for _, row in ipairs(body.body) do rows[#rows + 1] = row end
  end
  for _, row in ipairs(tbl.foot.rows) do rows[#rows + 1] = row end
  return rows
end

local function as_lines(inner)
  local lines = pandoc.Inlines{}
  for _, row in ipairs(rows_of(inner)) do
    local first = true
    for _, cell in ipairs(row.cells) do
      local text = pandoc.utils.blocks_to_inlines(cell.contents)
      if #text > 0 then
        if first and #lines > 0 then
          lines:insert(pandoc.LineBreak())
        elseif not first then
          lines:insert(pandoc.Space())
        end
        lines:extend(text)
        first = false
      end
    end
  end
  return pandoc.Plain(lines)
end

-- A table inside a table's cell as a tabular, which LaTeX nests where it
-- can't nest a longtable, with its head declared for tagging (a header
-- row, and a column where the pre-pass gave one) in a group of its own,
-- since \tagpdfsetup holds until it's changed, and only where it's
-- defined: an untagged PDF has no \tagpdfsetup, and LaTeX stopped on it
-- (pdf.standard: [], LaTeX 2026-06-01). Tagging makes it a Table inside
-- the cell's TD, which veraPDF passes (measured, LaTeX 2026-06-01). A cell
-- spanning rows needs multirow, which isn't loaded: such a table is
-- written as lines of text, as every inner table once was.
--
-- A footnote in such a table's cell stays a note, between the tabular's
-- pieces in a div, so the writer gives it as it gives one in the outer
-- table's cells: its mark (\footnotemark) in the cell, its text after
-- the outer table, with the outer table's own, in their order. Written
-- with the cell's text, as \footnote, it was a minipage's note in the
-- outer cell, lettered, where its text took a number another note had.
-- The writer puts a cell holding a div in a minipage, as it did the raw
-- block before.
local ALIGN = { AlignLeft = 'l', AlignCenter = 'c', AlignRight = 'r' }
local NOTE_MARK = 'OERINNERNOTE'

local function cell_latex(cell, notes)
  local contents = cell.contents:walk({
    Note = function(note)
      notes[#notes + 1] = note
      return pandoc.Str(NOTE_MARK .. #notes .. 'X')
    end,
  })
  local text = pandoc.write(pandoc.Pandoc(contents), 'latex')
  text = text:gsub('%s+$', ''):gsub('^%s+', ''):gsub('\n%s*\n', ' ')
  if cell.col_span > 1 then
    text = '\\multicolumn{' .. cell.col_span .. '}{c}{' .. text .. '}'
  end
  return text
end

-- The tabular's LaTeX, its notes put back where their marks stand.
local function with_notes(latex, notes)
  if #notes == 0 then
    return pandoc.RawBlock('latex', latex)
  end
  local inlines, last = pandoc.Inlines{}, 1
  for first, n, after in latex:gmatch('()' .. NOTE_MARK .. '(%d+)X()') do
    inlines:insert(pandoc.RawInline('latex', latex:sub(last, first - 1)))
    inlines:insert(notes[tonumber(n)])
    last = after
  end
  inlines:insert(pandoc.RawInline('latex', latex:sub(last)))
  return pandoc.Div({ pandoc.Plain(inlines) })
end

-- in_layout: the table this one is in is a layout table.
local function as_tabular(inner, in_layout)
  local head_rows = #inner.head.rows
  local head_columns = 0
  for _, body in ipairs(inner.bodies) do
    if body.row_head_columns > head_columns then
      head_columns = body.row_head_columns
    end
  end
  for _, row in ipairs(rows_of(inner)) do
    for _, cell in ipairs(row.cells) do
      if cell.row_span > 1 then
        return nil
      end
    end
  end
  local spec = {}
  for _, colspec in ipairs(inner.colspecs) do
    spec[#spec + 1] = ALIGN[colspec[1]] or 'l'
  end
  local lines, notes = {}, {}
  for i, row in ipairs(rows_of(inner)) do
    local cells = {}
    for _, cell in ipairs(row.cells) do
      cells[#cells + 1] = cell_latex(cell, notes)
    end
    lines[#lines + 1] = table.concat(cells, ' & ') .. ' \\\\'
    if i == head_rows then
      lines[#lines + 1] = '\\hline'
    end
  end
  local keys = {}
  if head_rows > 0 then
    local list = {}
    for i = 1, head_rows do list[#list + 1] = tostring(i) end
    keys[#keys + 1] = 'table/header-rows={' .. table.concat(list, ',') .. '}'
  end
  if head_columns > 0 then
    local list = {}
    for i = 1, head_columns do list[#list + 1] = tostring(i) end
    keys[#keys + 1] = 'table/header-columns={' .. table.concat(list, ',') .. '}'
  end
  local setup = #keys > 0 and tagging_setup(table.concat(keys, ',')) or ''
  if is_layout(inner) then
    setup = tagging_setup('table/tagging=div')
  elseif in_layout then
    table.insert(keys, 1, 'table/tagging=on')
    setup = tagging_setup(table.concat(keys, ',')):gsub('\\fi$', TABLE_PLUGS .. '\\fi')
  end
  return with_notes(
    '{' .. setup
    .. '\\begin{tabular}[t]{' .. table.concat(spec) .. '}\n'
    .. table.concat(lines, '\n') .. '\n\\end{tabular}}', notes)
end

local function flatten_nested(tbl)
  local layout = is_layout(tbl)
  for _, row in ipairs(rows_of(tbl)) do
    for _, cell in ipairs(row.cells) do
      cell.contents = cell.contents:walk({
        Table = function(inner)
          -- The innermost first: a table in this one's cells is written
          -- before this one is.
          flatten_nested(inner)
          local tabular = as_tabular(inner, layout)
          if tabular then
            return tabular
          end
          if not nested_seen then
            nested_seen = true
            io.stderr:write('[pdf-target] a table inside a table cell with a '
              .. 'cell spanning rows is written as lines of text\n')
          end
          return as_lines(inner)
        end
      })
    end
  end
end

-- A table the writer sets in l, c, or r columns, which don't wrap: one
-- whose columns have no widths, each of whose cells is one paragraph
-- with no line break, or none (isSimpleTable and colDescriptors,
-- Writers/LaTeX/Table.hs, 3.12.1), as an HTML page's table without a
-- <colgroup> is. A long cell ran past the page's edge: Prealgebra 2e's
-- Table 3.2, a worked example's steps. One wider than a line is given
-- widths, which the writer sets as p columns, which wrap: each column's
-- in proportion to its longest cell, and no narrower than its longest
-- word or formula, or a formula's longest piece. One whose longest words
-- alone are wider than a line is as narrow as it can be, and FIT_MACROS
-- sets it smaller as LaTeX measures it, as Instrumental Analysis's
-- tables of reactions needed; this had chosen LaTeX's \small or
-- \footnotesize for it from the characters it counted, which a table of
-- numbers outran in 12-point type (Introductory Business Statistics 2e's
-- F tables, up to 172 points too wide in \footnotesize).
local LINE = 70   -- characters in a line of the book class's 10pt type, about
local GAP = 3     -- the space between two columns, in characters

local function simple_cell(cell)
  local blocks = cell.contents
  if #blocks == 0 then return true end
  if #blocks > 1 or (blocks[1].t ~= 'Plain' and blocks[1].t ~= 'Para') then
    return false
  end
  local broken = false
  blocks[1]:walk({ LineBreak = function() broken = true end })
  return not broken
end

-- A cell's length and its longest word, in characters: a formula as many
-- as its TeX shows, and two more for each operator or relation, which
-- TeX sets with space around it; a picture, which the writer scales to
-- its column, a line, and no word. A formula's words are the pieces TeX
-- can't break it into (formula_pieces). A fill-in blank, a run of four or
-- more underscores, is three in a word, as PDF_MACROS draws one too long
-- for its line shorter, to three at the least: counted whole, a long
-- blank's column took the line from the next column's longest word, and
-- the table was set smaller for it.
local SPACED = { times = true, cdot = true, div = true, pm = true, mp = true,
                 le = true, leq = true, ge = true, geq = true, ne = true,
                 neq = true, approx = true, equiv = true, to = true,
                 rightarrow = true, Rightarrow = true }

-- The relations and binary operators a formula in text breaks after,
-- outside braces and \left...\right (TeXbook, chapter 18: \relpenalty
-- and \binoppenalty); a script after ^ or _ is part of its atom, so
-- Ag^+ doesn't break. An environment's lines (gathered, aligned) don't
-- break at all, each its own piece. Unicode's minus, times, and division
-- signs are operators too.
local BREAK_CHARS = { ['='] = true, ['<'] = true, ['>'] = true, ['+'] = true, ['-'] = true }
local BREAK_NAMES = {
  le = true, leq = true, ge = true, geq = true, ne = true, neq = true, approx = true,
  equiv = true, sim = true, simeq = true, cong = true, propto = true, ll = true, gg = true,
  to = true, gets = true, rightarrow = true, leftarrow = true, Rightarrow = true,
  Leftarrow = true, leftrightarrow = true, Leftrightarrow = true, longrightarrow = true,
  rightleftharpoons = true, leftrightharpoons = true, mapsto = true, ['in'] = true,
  subset = true, subseteq = true, times = true, cdot = true, div = true, pm = true,
  mp = true, ast = true, circ = true, bullet = true, oplus = true, otimes = true,
}

local function formula_pieces(tex)
  tex = tex:gsub('\226\136\146', '-'):gsub('\195\151', '\\times '):gsub('\195\183', '\\div ')
  if tex:find('\\begin%s*{') then
    local body = tex:gsub('\\begin%s*{[^}]*}', ''):gsub('\\end%s*{[^}]*}', '')
    local pieces = {}
    for line in (body .. '\\\\'):gmatch('(.-)\\\\') do pieces[#pieces + 1] = line end
    return pieces
  end
  local pieces, start, depth, i, n = {}, 1, 0, 1, #tex
  local function cut(at)
    pieces[#pieces + 1] = tex:sub(start, at)
    start = at + 1
  end
  while i <= n do
    local c = tex:sub(i, i)
    if c == '{' then
      depth, i = depth + 1, i + 1
    elseif c == '}' then
      depth, i = depth - 1, i + 1
    elseif c == '\\' then
      local name = tex:match('^%a+', i + 1)
      if name then
        local last = i + #name
        if name == 'left' then
          depth = depth + 1
        elseif name == 'right' then
          depth = depth - 1
        elseif depth == 0 and BREAK_NAMES[name] then
          cut(last)
        end
        i = last + 1
      else
        i = i + 2
      end
    elseif c == '^' or c == '_' then
      local j = i + 1
      while tex:sub(j, j):match('%s') do j = j + 1 end
      local d = tex:sub(j, j)
      if d == '{' then
        local level = 0
        repeat
          local e = tex:sub(j, j)
          if e == '{' then level = level + 1 elseif e == '}' then level = level - 1 end
          j = j + 1
        until level == 0 or j > n
        i = j
      elseif d == '\\' then
        i = j + 1 + #(tex:match('^%a+', j + 1) or 'x')
      else
        i = j + 1
      end
    elseif depth == 0 and BREAK_CHARS[c] then
      cut(i)
      i = i + 1
    else
      i = i + 1
    end
  end
  if start <= n then pieces[#pieces + 1] = tex:sub(start) end
  return pieces
end

-- How wide a formula is, in characters of text: a character or a symbol
-- one, a capital letter one and a half (Latin Modern's are about half as
-- wide again as its small letters, and a chemist's formulas are mostly
-- capitals), a script's (after ^ or _) seven tenths of that, as TeX sets
-- it in smaller type, a command that sets type or space rather than
-- drawing (\mathbf, \text, \left) none, and two for the space around
-- each operator or relation.
local DRAWS_NOTHING = {
  mathbf = true, mathrm = true, mathit = true, mathsf = true, mathtt = true,
  mathcal = true, mathbb = true, mathfrak = true, mathscr = true, mathnormal = true,
  text = true, textbf = true, textit = true, textrm = true, textsf = true, texttt = true,
  textnormal = true, operatorname = true, boldsymbol = true, bm = true,
  displaystyle = true, textstyle = true, scriptstyle = true, left = true, right = true,
  big = true, Big = true, bigg = true, Bigg = true, bigl = true, bigr = true,
  Bigl = true, Bigr = true, biggl = true, biggr = true, limits = true, nolimits = true,
  mathop = true, mathrel = true, mathbin = true, mathord = true, label = true,
  tag = true, nonumber = true, notag = true, begin = true, ['end'] = true,
}

local function formula_length(tex)
  local length, i, n, script, level = 0, 1, #tex, {}, 0
  local function weight() return script[level] and 0.7 or 1 end
  while i <= n do
    local c = tex:sub(i, i)
    if c == '{' then
      level = level + 1
      i = i + 1
    elseif c == '}' then
      script[level] = nil
      level = math.max(0, level - 1)
      i = i + 1
    elseif c == '^' or c == '_' then
      local j = i + 1
      while tex:sub(j, j):match('%s') do j = j + 1 end
      if tex:sub(j, j) == '{' then
        level = level + 1
        script[level] = true
        i = j + 1
      else
        local name = tex:sub(j, j) == '\\' and tex:match('^%a+', j + 1)
        if not (name and DRAWS_NOTHING[name]) then length = length + 0.7 end
        i = name and j + 1 + #name or j + 1
      end
    elseif c == '\\' then
      local name = tex:match('^%a+', i + 1)
      if name then
        if not DRAWS_NOTHING[name] then length = length + weight() end
        if SPACED[name] then length = length + 2 end
        i = i + 1 + #name
      else
        i = i + 2
      end
    elseif c:match('[%s&]') then
      i = i + 1
    else
      local width = c:match('[\192-\247]') and #(tex:match('^[\192-\247][\128-\191]*', i)) or 1
      length = length + weight() * (c:match('%u') and 1.5 or 1)
      if c:match('[-+=<>]') or tex:sub(i, i + width - 1):match('^\226\136\146')
          or tex:sub(i, i + width - 1):match('^\195[\151\183]') then
        length = length + 2
      end
      i = i + width
    end
  end
  return math.ceil(length)
end

-- A formula's width as LaTeX sets it in a table's cell, in text style, in
-- characters of text, for a worked example's steps (steps_widths): a
-- symbol a character, a capital, an m or a w, and an operator or a
-- relation but a dot, which are wider, one and a half; a function's name
-- (\sin, \log) a character a letter and one more, for the space TeX sets
-- beside it, but none where an opening delimiter follows, as in \log(x),
-- but for \left(, which makes a group TeX sets apart; a script four
-- fifths as wide as what it's set on, and one set under or over
-- something, as \underset and \limits set it, no wider than the wider of
-- the two, and a relation so set, as \overset{?}{=}, a relation; a space
-- in text seven tenths of a character, and none in \mathrm, where TeX
-- sets none; a fraction as wide as its wider part, both set as a script
-- is, and a little more; a root's sign one and a half; and the space TeX
-- sets around an operator or a relation between two others one and a
-- half, a half in a script. formula_length, which counts a fraction's two
-- parts one after the other and space around every operator, a script's
-- and a formula's first, counted College Algebra 2e's step formulas at
-- 1.76 times their width as Latin Modern Math sets them in 12-point type,
-- the median of the 301 in its first chapter's steps, 2.38 at the
-- ninetieth percentile; this counts them at 1.23, 1.27 at the ninetieth,
-- and none under 0.93: a little wider than they are, as a column that
-- mustn't break them wants them.
local FRACTIONS = { frac = true, tfrac = true, dfrac = true, cfrac = true, binom = true }
local FUNCTIONS = {
  arccos = true, arcsin = true, arctan = true, arg = true, cos = true, cosh = true,
  cot = true, coth = true, csc = true, deg = true, det = true, dim = true, exp = true,
  gcd = true, hom = true, inf = true, ker = true, lg = true, lim = true, liminf = true,
  limsup = true, ln = true, log = true, max = true, min = true, Pr = true, sec = true,
  sin = true, sinh = true, sup = true, tan = true, tanh = true,
}
local SET_AS_TEXT = { text = true, textrm = true, textit = true, textbf = true,
                      mathrm = true, mathit = true, mathbf = true, operatorname = true }
local TEXT_MODE = { text = true, textrm = true, textit = true, textbf = true }
local STACKED = { underset = true, overset = true, stackrel = true }
local OPENERS = { lbrack = true, lbrace = true, langle = true, lvert = true, lVert = true,
                  lceil = true, lfloor = true, bigl = true, Bigl = true, biggl = true,
                  Biggl = true }
local NO_GLYPH = { middle = true, cancel = true, bcancel = true, xcancel = true }

-- The end of the group a brace at i opens.
local function group_end(tex, i)
  local level, j = 0, i
  while j <= #tex do
    local c = tex:sub(j, j)
    if c == '\\' then
      j = j + 2
    else
      if c == '{' then level = level + 1 elseif c == '}' then level = level - 1 end
      if level == 0 then return j end
      j = j + 1
    end
  end
  return #tex
end

-- A command's argument at i: a group's insides, a command, or a symbol,
-- and where what follows it begins.
local function argument(tex, i)
  while tex:sub(i, i):match('%s') do i = i + 1 end
  local c = tex:sub(i, i)
  if c == '{' then
    local e = group_end(tex, i)
    return tex:sub(i + 1, e - 1), e + 1
  elseif c == '\\' then
    local name = tex:match('^%a+', i + 1) or tex:sub(i + 1, i + 1)
    return tex:sub(i, i + #name), i + 1 + #name
  end
  local width = c:match('[\192-\247]') and #(tex:match('^[\192-\247][\128-\191]*', i)) or 1
  return tex:sub(i, i + width - 1), i + width
end

-- Past a function's name at i: the limits set under and over it, after
-- \limits, and where what follows them begins; and whether an opening
-- delimiter follows it and any scripts, beside which TeX sets the name no
-- space, as it does beside the group \left( makes.
local function after_name(tex, i)
  local limits, j = {}, i
  while tex:sub(j, j):match('%s') do j = j + 1 end
  if tex:sub(j, j + 6) == '\\limits' then
    i = j + 7
    while true do
      while tex:sub(i, i):match('%s') do i = i + 1 end
      local c = tex:sub(i, i)
      if not (c == '^' or c == '_') then break end
      local body
      body, i = argument(tex, i + 1)
      limits[#limits + 1] = body
    end
  end
  j = i
  while true do
    while tex:sub(j, j):match('%s') do j = j + 1 end
    local c = tex:sub(j, j)
    if c == '^' or c == '_' then
      local _
      _, j = argument(tex, j + 1)
    elseif tex:sub(j, j + 8) == '\\nolimits' then
      j = j + 9
    else
      break
    end
  end
  local c = tex:sub(j, j)
  local name = c == '\\' and tex:match('^%a+', j + 1)
  local opens = c == '(' or c == '[' or tex:sub(j, j + 1) == '\\{'
    or (name and OPENERS[name]) or false
  return limits, i, opens
end

-- How wide a formula is, its type size the text's times size; script,
-- whether it's set in a script's style, where TeX sets no space around
-- an operator, and display, whether in display style, as a fraction is.
local function width_of(tex, size, script, display)
  local length, i, n, atoms, owed = 0, 1, #tex, 0, 0
  -- An atom of that width; an operator's space owed till an atom follows.
  local function add(w, operator)
    if operator then
      if atoms > 0 then owed = (script and 0.5 or 1.5) * size end
    else
      length, owed = length + owed, 0
    end
    length, atoms = length + w, atoms + 1
  end
  while i <= n do
    local c = tex:sub(i, i)
    if c == '{' then
      local e = group_end(tex, i)
      add(width_of(tex:sub(i + 1, e - 1), size, script, display))
      i = e + 1
    elseif c == '^' or c == '_' then
      local body
      body, i = argument(tex, i + 1)
      length = length + width_of(body, 0.8 * size, true, display)
    elseif c == '\\' then
      local name = tex:match('^%a+', i + 1)
      if not name then
        local d = tex:sub(i + 1, i + 1)
        if d == ',' then
          length = length + 0.35 * size
        elseif d == ' ' or d == ';' then
          length = length + 0.55 * size
        elseif d:match('[{}|%%$#&_]') then
          add(size)
        end
        i = i + 2
      else
        i = i + 1 + #name
        if FRACTIONS[name] then
          local top, bottom
          top, i = argument(tex, i)
          bottom, i = argument(tex, i)
          local large = name == 'dfrac' or (display and not script)
          local part = large and size or 0.8 * size
          add(math.max(width_of(top, part, not large, display),
                       width_of(bottom, part, not large, display)) + 0.6 * size)
        elseif name == 'sqrt' then
          local degree = 0
          if tex:sub(i, i) == '[' then
            i = (tex:find(']', i, true) or i) + 1
            degree = 0.5 * size
          end
          local body
          body, i = argument(tex, i)
          add(width_of(body, size, script, display) + 1.5 * size + degree)
        elseif SET_AS_TEXT[name] then
          local body
          body, i = argument(tex, i)
          local _, spaces = body:gsub('%s+', '')
          if not TEXT_MODE[name] then spaces = 0 end
          add(width_of(body, size, script, display) + 0.7 * size * spaces)
        elseif STACKED[name] then
          local over, under
          over, i = argument(tex, i)
          under, i = argument(tex, i)
          local base = under:match('^%s*(.-)%s*$')
          local command = base:match('^\\(%a+)$')
          add(math.max(width_of(over, 0.8 * size, true, display),
                       width_of(under, size, script, display)),
              name == 'stackrel' or BREAK_CHARS[base] or (command and BREAK_NAMES[command]))
        elseif name == 'mspace' then
          local body
          body, i = argument(tex, i)
          length = length + (tonumber(body:match('^%s*([%d.]+)%s*mu')) or 0) / 8.7 * size
        elseif name == 'quad' or name == 'qquad' then
          length = length + (name == 'quad' and 2 or 4) * size
        elseif FUNCTIONS[name] then
          local limits, opens
          limits, i, opens = after_name(tex, i)
          local width = #name * size
          for _, body in ipairs(limits) do
            width = math.max(width, width_of(body, 0.8 * size, true, display))
          end
          add(width + (opens and 0 or size))
        elseif not (DRAWS_NOTHING[name] or NO_GLYPH[name]) then
          local operator = SPACED[name] or BREAK_NAMES[name]
          add((operator and name ~= 'cdot') and 1.5 * size or size, operator)
        end
      end
    elseif c:match('[%s&]') then
      i = i + 1
    elseif c == '~' then
      length, i = length + 0.7 * size, i + 1
    else
      local width = c:match('[\192-\247]') and #(tex:match('^[\192-\247][\128-\191]*', i)) or 1
      local glyph = tex:sub(i, i + width - 1)
      local operator = c:match('[-+=<>]') ~= nil or glyph == '\226\136\146'
        or glyph:match('^\195[\151\183]') ~= nil
      add(size * ((operator or c:match('[%umwMW]')) and 1.5 or 1), operator)
      i = i + width
    end
  end
  return length
end

local function formula_width(tex)
  return math.ceil(width_of(tex, 1, false, tex:find('\\displaystyle', 1, true) ~= nil))
end

-- A fill-in blank, a run of four or more underscores the blank pass
-- marks (blanks, below), counts as three in a cell's longest word, the
-- shortest LaTeX draws it to fit its column, and whole in the cell's
-- length, as it's drawn where there's room. Underscores the pass leaves
-- alone, in code, a link, an underline, a strikeout, or a mark, LaTeX
-- doesn't draw shorter, and they count whole in both.
local function blanks_counted(block)
  local skip = function(element) return element, false end
  return pandoc.Blocks{ block }:walk{
    traverse = 'topdown', Image = skip, Link = skip, Underline = skip, Strikeout = skip,
    Span = function(span) if span.classes:includes('mark') then return span, false end end,
    Str = function(str)
      if str.text:find('____', 1, true) then
        return pandoc.Str((str.text:gsub('____+', '___')))
      end
    end }
end

local function cell_size(cell)
  local length, longest = 0, 0
  local counted = {
    Math = function(math_)
      local words = {}
      for _, piece in ipairs(formula_pieces(math_.text)) do
        local size = formula_length(piece)
        if size > 0 then words[#words + 1] = ('m'):rep(size) end
      end
      return pandoc.Str(#words > 0 and table.concat(words, ' ') or 'm')
    end,
    Image = function() return pandoc.Str((' '):rep(LINE)) end,
    LineBreak = function() return pandoc.Str('\n') end,
  }
  for _, block in ipairs(cell.contents) do
    local text = stringify(pandoc.Blocks{ block }:walk(counted))
    for line in (text .. '\n'):gmatch('(.-)\n') do
      length = math.max(length, utf8.len(line) or #line)
    end
    for word in stringify(blanks_counted(block):walk(counted)):gmatch('%S+') do
      longest = math.max(longest, utf8.len(word) or #word)
    end
  end
  return length, longest
end

-- A table with widths, its source's or ones its reader gave it (Pandoc's
-- HTML reader gives a table whose cells hold more than a paragraph equal
-- widths): a column narrower than its longest word or formula, which
-- LaTeX can't break, ran into the next one, as Instrumental Analysis's
-- columns of reactions did. Such a column is widened to it, and the
-- columns with room to spare give it up in proportion to what they
-- spare; where the longest words together are wider than a line, the
-- table is as narrow as it can be, each column as wide as its longest
-- word, and FIT_MACROS sets it smaller. Widths that hold their words are
-- left as they are.
local function widen_to_words(tbl, word)
  local count = #tbl.colspecs
  local room = LINE - GAP * (count - 1)
  local least, sum, short = {}, 0, false
  for j = 1, count do
    least[j] = word[j] / room
    sum = sum + least[j]
    if least[j] > tbl.colspecs[j][2] then short = true end
  end
  if not short then return end
  if sum > 1 then
    for j = 1, count do
      tbl.colspecs[j] = { tbl.colspecs[j][1], least[j] }
    end
    return
  end
  local deficit, spare = 0, 0
  for j = 1, count do
    local width = tbl.colspecs[j][2]
    if least[j] > width then
      deficit = deficit + least[j] - width
    else
      spare = spare + width - least[j]
    end
  end
  for j = 1, count do
    local width = tbl.colspecs[j][2]
    if least[j] > width then
      tbl.colspecs[j] = { tbl.colspecs[j][1], least[j] }
    elseif spare > 0 then
      tbl.colspecs[j] = { tbl.colspecs[j][1],
                          width - deficit * (width - least[j]) / spare }
    end
  end
end

-- A cell's one formula, the TeX of it, where that's all it holds but
-- space and the braces around a formula with an alignment in it
-- (braced_math); or nil. Taken for words, such a formula, as OpenStax
-- spaces a step's (an empty matrix's &, 20 of College Algebra 2e's 160
-- tables of steps and 38 of Precalculus 2e's 142), left its column a
-- column of words, and the table one with two columns of words.
local function lone_formula(cell)
  local blocks = cell.contents
  if #blocks ~= 1 or (blocks[1].t ~= 'Plain' and blocks[1].t ~= 'Para') then return nil end
  local found
  for _, inline in ipairs(blocks[1].content) do
    if inline.t == 'Math' and not found then
      found = inline.text
    elseif not (inline.t == 'Space' or inline.t == 'SoftBreak'
                or inline.t == 'RawInline' and (inline.text == '{' or inline.text == '}')) then
      return nil
    end
  end
  return found
end

-- The widest formula in a cell of words, as formula_width counts it, or
-- 0: a formula in a worked example's steps doesn't break (Table), so a
-- step's reason is no narrower than its widest formula, given MATH_ROOM.
local function widest_formula(cell)
  local widest = 0
  pandoc.Blocks(cell.contents):walk({ Math = function(math_)
    widest = math.max(widest, formula_width(math_.text))
  end })
  return widest
end

-- The counts of a worked example's steps. Where LuaTeX sets the PDF,
-- steps with one column of words are laid out by what LaTeX measures of
-- them (steps_spec, below), so these counts lay out the steps a TeX
-- without Lua sets, those with no column of words or more than one, and
-- those the writer floats; give the words their part of the line on
-- LaTeX's first run; and are the shares the LaTeX gives each column. The
-- figures below were measured when the counts laid out every PDF.
--
-- A worked example's steps the CNX unpacker lays out in a table (class
-- formula-steps), its math cell for cell and its words, a step's reason
-- or instruction, in a column of their own: at its own width where the
-- line has room for it, each column as wide as its widest cell; and
-- where it hasn't, each column of math as wide as its widest formula,
-- given MATH_ROOM, and the words wrapping in what's left of the line, no
-- narrower than their longest word or their widest formula, given
-- MATH_ROOM too. Counted by formula_width, which counts a formula closer
-- to its width than formula_length: by formula_length's count, College
-- Algebra 2e's steps would take columns wider than their math, and a
-- table that fits its line would be set across it, its words wrapped.
-- Where the formulas and the longest words together are wider than the
-- line by that count, the words are as wide as their longest and the
-- formulas share what's left by their counts. Seven of College Algebra
-- 2e's first chapter's 51 tables of steps are so; set as other tables
-- are (fit_to_line), six of them, in Noto Sans, would be set in smaller
-- type to fit their formulas to their columns, and shared so, three were
-- (MATH_ROOM). Where that would leave the formulas less than FIT_FLOOR of
-- their counts, as a reason holding a long formula can, which no fit to
-- the line makes up for, every formula, a reason's too, is given the same
-- part of its count, each column of words no narrower than its longest
-- word, so that the fit sets them smaller alike: a word given less than
-- its width would be broken at a hyphen, where a formula too wide is
-- fitted. Precalculus 2e's Example 7 in 12.2, whose reason holds a
-- formula about as wide as its column of math's widest, would otherwise
-- have its formulas given less than a third of their counts, and be set
-- at half its size, 353 points wider than the text; it was at three
-- quarters, 2 points wider than the text. A word is as cell_size counts
-- it, a piece of a formula between the places TeX could break it among
-- them, though a formula in steps doesn't break: held at its words
-- alone, Calculus Volume 2's steps in 3.3, at three quarters of their
-- size, would have been 108 points wider than the text, where they were
-- 36, their reason's formula counted narrower than LaTeX sets it. A
-- formula still wider than its column isn't broken but fitted (Table).
-- Whether it was set so; steps whose longest words alone fill the line
-- are set as other tables are, and steps whose reason's formula alone
-- fills it, given MATH_ROOM, are shared, even where their cells' length
-- as cell_size counts it, a function's name a character, would fit.
--
-- MATH_ROOM is the part of its count a formula is given, in a column of
-- math or among the words: a tenth more. Pandoc's template scales Latin
-- Modern Math, a formula's face where a book names none, to the height
-- of the text's small letters, and Noto Sans's, the face of OpenStax's
-- math books, are 24 percent taller than Latin Modern's, so a formula
-- is set wider than the count, which is Latin Modern's: in College
-- Algebra 2e's first chapter, in Noto Sans, without it 10 of its 51
-- tables of steps would have had a formula wider than its column, 9 set
-- smaller to fit it (FIT_MACROS); with it, 4 had, 3 set smaller, which
-- were wider than the line even in columns as wide as LaTeX measures
-- their widest formula or word.
local MATH_ROOM = 1.1

-- The least part of its size FIT_MACROS sets a table in to fit its line
-- (latexbuild.py's FIT_FLOOR).
local FIT_FLOOR = 0.75

-- Which of a worked example's columns hold formulas, each cell one or
-- nothing (true), which hold words (false), and which nothing at all
-- (nil), where each of its rows has a cell for each column and no cell is
-- across columns or rows; nil where not.
local function steps_columns(tbl)
  local count = #tbl.colspecs
  local formulas, rows = {}, rows_of(tbl)
  for _, row in ipairs(rows) do
    if #row.cells ~= count then return nil end
    for j, cell in ipairs(row.cells) do
      if (cell.col_span or 1) ~= 1 or (cell.row_span or 1) ~= 1 then return nil end
      local formula = lone_formula(cell)
      if formula then
        formulas[j] = formulas[j] ~= false
      elseif #cell.contents > 0 and stringify(cell.contents):match('%S') then
        formulas[j] = false
      end
    end
  end
  return formulas, rows
end

local function steps_widths(tbl)
  local count = #tbl.colspecs
  local formulas, rows = steps_columns(tbl)
  if not formulas then return false end
  local need, word, long, reach = {}, {}, {}, {}
  for j = 1, count do need[j], word[j], long[j], reach[j] = 0, 0, 0, 0 end
  for _, row in ipairs(rows) do
    for j, cell in ipairs(row.cells) do
      if formulas[j] then
        local formula = lone_formula(cell)
        if formula then need[j] = math.max(need[j], formula_width(formula)) end
      else
        local length, longest = cell_size(cell)
        need[j] = math.max(need[j], length)
        long[j] = math.max(long[j], longest)
        reach[j] = math.max(reach[j], MATH_ROOM * widest_formula(cell))
        word[j] = math.max(long[j], reach[j])
      end
    end
  end
  local room = LINE - GAP * (count - 1)
  local total, maths, least, words = 0, 0, 0, 0
  for j = 1, count do
    total = total + need[j]
    if formulas[j] then
      need[j] = MATH_ROOM * need[j]
      maths = maths + need[j]
    else
      least = least + word[j]
      words = words + long[j]
    end
  end
  if room <= words then return false end
  if total <= room and least < room then return true end
  local share, held = {}, {}
  if maths + least > room then
    -- part is of the formulas' counts given MATH_ROOM.
    local part = (room - least) / maths
    if part * MATH_ROOM >= FIT_FLOOR then
      for j = 1, count do
        share[j] = formulas[j] and need[j] * part or word[j]
      end
    else
      -- Every formula the same part of its count, a column of words no
      -- narrower than its longest word, held at that where its widest
      -- formula so shared is narrower, the part found again with those
      -- columns held.
      repeat
        local fixed, scaled = 0, 0
        for j = 1, count do
          if formulas[j] then
            scaled = scaled + need[j]
          elseif held[j] then
            fixed = fixed + long[j]
          else
            scaled = scaled + reach[j]
          end
        end
        part = (room - fixed) / scaled
        local again = false
        for j = 1, count do
          if not formulas[j] and not held[j] and reach[j] * part < long[j] then
            held[j], again = true, true
          end
        end
      until not again
      for j = 1, count do
        share[j] = formulas[j] and need[j] * part or (held[j] and long[j] or reach[j] * part)
      end
    end
    for j = 1, count do
      tbl.colspecs[j] = { tbl.colspecs[j][1], share[j] / room }
    end
    return true
  end
  -- What's left shared among the columns of words by need, one whose
  -- share is less than its longest word held at that, as fit_to_line
  -- shares.
  repeat
    local held_total, free_need = maths, 0
    for j = 1, count do
      if not formulas[j] then
        if held[j] then held_total = held_total + word[j] else free_need = free_need + need[j] end
      end
    end
    local again = false
    for j = 1, count do
      if formulas[j] then
        share[j] = need[j]
      elseif held[j] then
        share[j] = word[j]
      else
        share[j] = free_need > 0 and (room - held_total) * need[j] / free_need or 0
        if share[j] < word[j] then held[j], again = true, true end
      end
    end
  until not again
  for j = 1, count do
    tbl.colspecs[j] = { tbl.colspecs[j][1], share[j] / room }
  end
  return true
end

local function fit_to_line(tbl)
  local count = #tbl.colspecs
  if count < 2 then return end
  local given = tbl.colspecs[1][2] ~= nil
  for _, spec in ipairs(tbl.colspecs) do
    if (spec[2] ~= nil) ~= given then return end
  end
  if not given and tbl.classes:includes('formula-steps') and steps_widths(tbl) then return end
  local need, word = {}, {}
  for j = 1, count do need[j], word[j] = 1, 1 end
  local spanning = {}  -- cells across columns: { first, last, length, longest }
  local covered = {}   -- grid column -> rows a cell spanning rows still covers
  for _, row in ipairs(rows_of(tbl)) do
    local column = 1
    for _, cell in ipairs(row.cells) do
      if not given and not simple_cell(cell) then return end
      while (covered[column] or 0) > 0 do column = column + 1 end
      local span = cell.col_span or 1
      local length, longest = cell_size(cell)
      if span == 1 and column <= count then
        need[column] = math.max(need[column], length)
        word[column] = math.max(word[column], longest)
      elseif column <= count then
        spanning[#spanning + 1] = { column, math.min(count, column + span - 1),
                                    length, longest }
      end
      for c = column, column + span - 1 do
        covered[c] = math.max(covered[c] or 0, cell.row_span or 1)
      end
      column = column + span
    end
    for c, left in pairs(covered) do covered[c] = left - 1 end
  end
  -- A cell across columns needs as much of them together as it holds,
  -- shared among them where they'd hold less.
  for _, cell in ipairs(spanning) do
    local first, last, length, longest = table.unpack(cell)
    local columns, held = last - first + 1, GAP * (last - first)
    for j = first, last do held = held + need[j] end
    for j = first, last do
      if held < length then need[j] = need[j] + (length - held) / columns end
      word[j] = math.max(word[j], longest / columns)
    end
  end
  if given then return widen_to_words(tbl, word) end
  local room, total = LINE - GAP * (count - 1), 0
  -- More columns than a line has room to space, by this count, as a table
  -- of a few dozen numbers side by side has: as the writer sets them, each
  -- as wide as its widest cell, for FIT_MACROS to fit; the shares below
  -- would be of no room at all.
  if room <= 0 then return end
  for j = 1, count do total = total + need[j] end
  if total <= room then return end
  local least, sum = {}, 0
  for j = 1, count do
    least[j] = word[j] / room
    sum = sum + least[j]
  end
  if sum > 1 then
    -- Its longest words too wide for a line: as narrow as it can be,
    -- which FIT_MACROS sets smaller to fit. A table with nothing to wrap,
    -- every cell a word or two, a table of numbers, is narrowest in the
    -- columns the writer gives it, each as wide as its widest cell; one
    -- with cells to wrap, in columns as wide as their longest words.
    local wraps = false
    for j = 1, count do
      if need[j] > word[j] then wraps = true end
    end
    if wraps then
      for j = 1, count do
        tbl.colspecs[j] = { tbl.colspecs[j][1], least[j] }
      end
    end
    return
  end
  -- Shares by need, a column whose share is less than its least held at
  -- its least, and the rest shared again among the others.
  local share, held = {}, {}
  repeat
    local held_total, free_need = 0, 0
    for j = 1, count do
      if held[j] then held_total = held_total + least[j] else free_need = free_need + need[j] end
    end
    local again = false
    for j = 1, count do
      if held[j] then
        share[j] = least[j]
      else
        share[j] = (1 - held_total) * need[j] / free_need
        if share[j] < least[j] then held[j], again = true, true end
      end
    end
  until not again
  for j = 1, count do
    tbl.colspecs[j] = { tbl.colspecs[j][1], share[j] }
  end
end

-- A worked example's steps (steps_columns) with one column of words, as
-- the CNX unpacker writes them, laid out by what LaTeX measures of them
-- where LuaTeX sets them (FIT_MACROS' \OERFitStepsTable): each column of
-- formulas as wide as its widest, and the column of words, which wraps,
-- as wide as its longest paragraph set as one line, where the table so
-- fits its line, and otherwise as wide as the line leaves it, no narrower
-- than its longest piece TeX can't break; where even that's wider than the
-- line, the table's spaces are narrowed and its type set smaller, as
-- another table's are. The counts above give the words their part of the
-- line on LaTeX's first run, and lay the table out for a TeX without Lua,
-- which sets the writer's columns: the letters of the columns'
-- alignments, and for each column m, one of formulas, or the column of
-- words' part of the line by the counts, their share where they set it
-- across the line. Nil for steps with no column of words or more than
-- one, which the counts lay out.
local function steps_spec(tbl)
  if not tbl.classes:includes('formula-steps') then return nil end
  local formulas, rows = steps_columns(tbl)
  if not formulas then return nil end
  local count, words = #tbl.colspecs, 0
  for j = 1, count do
    if formulas[j] == false then words = words + 1 end
  end
  if words ~= 1 then return nil end
  local room = LINE - GAP * (count - 1)
  local letters, parts, need = {}, {}, {}
  for j = 1, count do
    local align = tbl.colspecs[j][1]
    letters[j] = (align == 'AlignRight' and 'r') or (align == 'AlignCenter' and 'c') or 'l'
    need[j] = 0
  end
  for _, row in ipairs(rows) do
    for j, cell in ipairs(row.cells) do
      if formulas[j] == false then need[j] = math.max(need[j], (cell_size(cell))) end
    end
  end
  for j = 1, count do
    if formulas[j] == false then
      parts[j] = string.format('%.4f', tbl.colspecs[j][2] or math.min(1, need[j] / room))
    else
      parts[j] = 'm'
    end
  end
  return { table.concat(letters), table.concat(parts, ',') }
end

-- 19. A table, or a formula TeX can't break, wider than its line: Pandoc's
-- writer leaves both as they are, and LaTeX sets them past the line's end,
-- into the margin or off the paper (College Algebra 2e's first chapter, 28
-- formulas by up to 224 points; Introductory Business Statistics 2e's F
-- tables, by up to 172 in \footnotesize). Each is numbered and set in a
-- group, for FIT_MACROS (latexbuild.py) to measure as LaTeX sets it and
-- fit to its line on a later run: its spaces narrowed, then its type set
-- smaller. The numbers are this run's, in the order the filter meets them,
-- the same on every run of LaTeX, which reads them from the same LaTeX.
local fitted = 0
local function next_fit()
  fitted = fitted + 1
  return tostring(fitted)
end

-- Whether the writer sets a table's columns as p columns, which wrap: any
-- column with a width, or any cell more than one paragraph or holding a
-- line break (isSimpleTable, Writers/LaTeX/Table.hs, 3.12.1). A table in
-- l, c, and r columns is as wide as its cells, which shrink with its type.
local function wrapping(tbl)
  for _, spec in ipairs(tbl.colspecs) do
    if spec[2] ~= nil then return true end
  end
  for _, row in ipairs(rows_of(tbl)) do
    for _, cell in ipairs(row.cells) do
      if not simple_cell(cell) then return true end
    end
  end
  return false
end

local sized_table

-- A table not in a table's cell (19) in a group FIT_MACROS fits: \OERFitTable
-- with its number, its columns, and whether they wrap, or for a worked
-- example's steps LaTeX lays out \OERFitStepsTable (steps_spec), and
-- \OERFitTableEnd, which reads the widths longtable recorded. A layout
-- table's caption, a paragraph before it, is before the group, in the
-- text's type. A worked example's steps (steps_widths) break no formula
-- over lines: TeX breaks a formula in text after a relation or an
-- operator, and FIT_MACROS measures a column by the longest piece TeX
-- can't break, so that otherwise a formula wider than its column would be
-- broken, not fitted, as one of the steps of College Algebra 2e's Example
-- 6 (e), in section 1.1, would be. And they're drawn without the rules the
-- writer draws above and below every table (booktabs' \toprule and
-- \bottomrule, each followed by \noalign{}, which is left alone), as
-- OpenStax sets a worked example's steps, a formula with no lines: drawn,
-- they set the steps off as a table of data. Steps have no head, and so
-- no rule under it.
local STEPS_OPEN = '\\binoppenalty=10000 \\relpenalty=10000 '
  .. '\\def\\toprule{}\\def\\bottomrule{}'

function Table(tbl)
  local nested = tbl.attributes[IN_CELL] ~= nil
  local steps = tbl.classes:includes('formula-steps')
  local result, wraps, columns, lead, measured = sized_table(tbl)
  if nested then return result end
  local id = next_fit()
  local open = measured
    and ('{\\OERFitStepsTable{' .. id .. '}{' .. columns .. '}{' .. measured[1] .. '}{'
         .. measured[2] .. '}')
    or ('{\\OERFitTable{' .. id .. '}{' .. columns .. '}{' .. (wraps and '1' or '0') .. '}')
  local function fitted(blocks)
    local out = pandoc.Blocks{}
    for i = 1, lead or 0 do out:insert(blocks[i]) end
    out:insert(pandoc.RawBlock('latex', open .. (steps and STEPS_OPEN or '')))
    for i = (lead or 0) + 1, #blocks do out:insert(blocks[i]) end
    out:insert(pandoc.RawBlock('latex', '\\OERFitTableEnd{' .. id .. '}}'))
    return out
  end
  if result.t == 'Div' then
    result.content = fitted(result.content)
    return result
  elseif result.t then
    return fitted({ result })
  end
  return fitted(result)
end

sized_table = function(tbl)
  local cell = in_cell(tbl)
  tbl = tbl:walk(braced_math)
  flatten_nested(tbl)
  unquote_cells(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    unquote_cells(body.head)
    unquote_cells(body.body)
  end
  unquote_cells(tbl.foot.rows)
  fit_to_line(tbl)
  local measured = not cell and steps_spec(tbl) or nil
  local wraps, count = wrapping(tbl), #tbl.colspecs
  local columns = 0
  for _, body in ipairs(tbl.bodies) do
    if body.row_head_columns > columns then
      columns = body.row_head_columns
    end
  end
  if is_layout(tbl) then
    -- No table's caption, since the PDF has no table: a paragraph before
    -- it, which LaTeX doesn't number as a table's, and which a longtable's
    -- head, tagged as a division's, would have held as a header cell with
    -- no row (TH in a NonStruct). Its id is a div's, an anchor before it:
    -- the writer gives a table with an id and no caption an empty one to
    -- hold its \label (Writers/LaTeX/Table.hs, 3.12), which LaTeX numbered
    -- ("Table 3") in that head.
    local blocks = {}
    for _, block in ipairs(tbl.caption and tbl.caption.long or {}) do
      blocks[#blocks + 1] = block.t == 'Plain' and pandoc.Para(block.content) or block
    end
    local lead = #blocks
    tbl.caption = pandoc.Caption()
    local id = tbl.identifier
    tbl.identifier = ''
    blocks[#blocks + 1] = pandoc.RawBlock('latex', LAYOUT_OPEN)
    blocks[#blocks + 1] = tbl
    blocks[#blocks + 1] = pandoc.RawBlock('latex', '}')
    if id ~= '' then
      return pandoc.Div(blocks, pandoc.Attr(id)), wraps, count, lead, measured
    end
    return blocks, wraps, count, lead, measured
  end
  -- A data table's id with no caption to hold it is a div's too, an anchor
  -- before the table: the writer's empty caption numbered a table the book
  -- never numbered ("Table 3"), and one of class unnumbered, which gets no
  -- caption, got no \label either, so a link to it went nowhere.
  local id = nil
  if tbl.identifier ~= '' and #tbl.caption.long == 0
      and not (tbl.caption.short and #tbl.caption.short > 0) then
    id = tbl.identifier
    tbl.identifier = ''
  end
  local own = not cell and own_label(tbl.caption, TABLE_WORDS)
  local blocks = { tbl }
  if columns > 0 then
    local list = {}
    for i = 1, columns do
      list[#list + 1] = tostring(i)
    end
    blocks = {
      pandoc.RawBlock("latex", tagging_setup("table/header-columns={"
                      .. table.concat(list, ",") .. "}")),
      tbl,
      pandoc.RawBlock("latex", tagging_setup("table/header-columns={}")),
    }
  end
  if own then blocks = without_label(blocks) end
  if id then return pandoc.Div(blocks, pandoc.Attr(id)), wraps, count, nil, measured end
  if columns == 0 and not own then return tbl, wraps, count, nil, measured end
  return blocks, wraps, count, nil, measured
end

local function decorative(img)
  return img.attributes["aria-hidden"] == "true"
    or img.attributes["role"] == "presentation"
end

-- An image with a width or a height (17): the writer sets it at that
-- size, where one with neither it scales to fit its line and the page in
-- \pandocbounded (Writers/LaTeX.hs, 3.12.1). A LibreTexts page gives
-- each picture its width in pixels, which the writer takes at 96 an
-- inch: 217 of Instrumental Analysis's were wider than the line, 82 of
-- them past the page's edge. Such an image is set in the same macro,
-- which leaves one that fits as it is; \protect before it, as the writer
-- puts before its own in a heading. A size is one the writer reads
-- (lengthToDim, Text/Pandoc/ImageSize.hs): a number, then a unit it knows
-- or none.
local UNITS = { [""] = true, px = true, cm = true, mm = true, ["in"] = true,
                inch = true, ["%"] = true, pt = true, pc = true, em = true }

local function size(value)
  if not value then return false end
  local number, unit = value:match("^([%d.]*)%s*(.-)$")
  return (number:match("^%d+$") or number:match("^%d+%.%d+$")) ~= nil
    and UNITS[unit] == true
end

local function bounded(img)
  if size(img.attributes["width"]) or size(img.attributes["height"]) then
    return { pandoc.RawInline("latex", "\\protect\\pandocbounded{"), img,
             pandoc.RawInline("latex", "}") }
  end
  return { img }
end

function Image(img)
  -- An alt text with a line end in it: the reader keeps an alt key's raw
  -- text in one Str, line ends and all, and the writer writes it as it is,
  -- so a blank line in it ended the paragraph inside \pandocbounded, where
  -- LaTeX stopped ("Paragraph ended before \pandocbounded was complete":
  -- OpenIntro's descriptions of two paragraphs). Its spaces made single.
  local changed = false
  if img.attributes["alt"] and img.attributes["alt"]:find("\n") then
    img.attributes["alt"] = squash(img.attributes["alt"])
    changed = true
  end
  local caption = pandoc.Inlines{}
  for _, inline in ipairs(img.caption) do
    if inline.t == "Str" and inline.text:find("\n") then
      inline = pandoc.Str(squash(inline.text))
      changed = true
    end
    caption:insert(inline)
  end
  img.caption = caption
  if decorative(img) and stringify(img.caption) == "" then
    -- The filter writes alt="" for HTML, and the writer passes an alt
    -- attribute on as the alt key, even empty; alt={} after the artifact
    -- key sets the image back to a figure, whose missing text LaTeX then
    -- fills with the file name.
    img.attributes["alt"] = nil
    local set = bounded(img)
    table.insert(set, 1, pandoc.RawInline("latex", "{\\OERArtifactGraphics"))
    table.insert(set, pandoc.RawInline("latex", "}"))
    return set
  end
  local set = bounded(img)
  if changed or #set > 1 then
    return set
  end
end

function Link(link)
  local text = squash(stringify(link.content))
  local description = squash(link.title or "")
  if description == "" then
    description = squash(link.attributes["aria-label"] or "")
  end
  local contents = text
  if description ~= "" and description ~= text then
    contents = (text ~= "" and (text .. " (" .. description .. ")"))
      or description
  end
  if contents == "" then
    return nil
  end
  -- Set for this link and cleared after it, so a link LaTeX makes on
  -- its own (a footnote mark, a contents line) never inherits it.
  return {
    pandoc.RawInline("latex",
                     "\\OERLinkContents{" .. unjoined(tex_escape(contents)) .. "}"),
    link,
    pandoc.RawInline("latex", "\\OERLinkContentsReset{}"),
  }
end

-- Figures the writer can't make one LaTeX figure of (Writers/LaTeX.hs,
-- 3.12). A figure inside a figure is written as the inner one's content
-- with an empty \caption{} of its own before the outer one's, so the PDF
-- numbers two captions in one figure, and tagged, the figure (an Aside)
-- holds more than one Caption, not all first or last, which PDF 2.0 and
-- PDF/UA-2 forbid (ISO 32000-2, 14.8.4.8.4; ISO 14289-2, 8.2.5.27; what
-- veraPDF reported of Instrumental Analysis's eight such figures): the
-- inner figure's content stands in the outer one, and its caption, if it
-- had one, as a paragraph under it. So does one in a div inside the
-- figure, as LibreTexts sets two pictures side by side (<figure><div
-- class="row"><figure>…), which the writer writes the same way.
-- A figure holding only a table is written as the table, which can't
-- float, and the figure's caption is dropped: the caption becomes the
-- table's, when the table has none.
local function caption_blocks(caption)
  return caption and caption.long or pandoc.Blocks{}
end

-- Pictures side by side, as a page saved from the web sets them in a row
-- of its grid (a div of class row holding figures, each a picture with no
-- caption: LibreTexts's two, its caption saying which is left and which
-- right), are one line of pictures, each its share of the line, less the
-- space between them, or its own width where that's less; the pages
-- draw them in a row too (page.css). With a caption of their own, they
-- stand one under another, each caption under its picture.
local ROW_GAP = 4         -- percent of the line between two pictures
local LINE_POINTS = 345   -- the book class's line at 10pt, in points
local POINTS = { px = 0.75, pt = 1, ['in'] = 72, inch = 72, cm = 72 / 2.54,
                 mm = 72 / 25.4, pc = 12 }

local function picture_of(block)
  if block.t ~= 'Figure' or #caption_blocks(block.caption) > 0
      or #block.content ~= 1
      or (block.content[1].t ~= 'Plain' and block.content[1].t ~= 'Para') then
    return nil
  end
  local image = nil
  for _, inline in ipairs(block.content[1].content) do
    if inline.t == 'Image' and not image then
      image = inline
    elseif inline.t ~= 'Space' and inline.t ~= 'SoftBreak' then
      return nil
    end
  end
  return image
end

local function narrower(width, share)
  local number, unit = (width or ''):match('^%s*([%d.]+)%s*(%a*%%?)%s*$')
  number = tonumber(number)
  if not number then return false end
  if unit == '%' then return number <= share end
  local points = POINTS[unit ~= '' and unit or 'px']
  return points ~= nil and number * points <= share / 100 * LINE_POINTS
end

local function side_by_side(div)
  if not div.classes:includes('row') or #div.content < 2 then return nil end
  local images = {}
  for _, block in ipairs(div.content) do
    images[#images + 1] = picture_of(block)
    if not images[#images] then return nil end
  end
  local share = (100 - ROW_GAP * (#images - 1)) / #images
  -- A paragraph from the start, so each picture is one of the same line,
  -- the first not set before it in the float.
  local line = pandoc.Inlines{ pandoc.RawInline('latex', '\\leavevmode') }
  for i, image in ipairs(images) do
    if i > 1 then line:insert(pandoc.RawInline('latex', '\\hfill')) end
    if not narrower(image.attributes.width, share) then
      image.attributes.width = ('%.1f%%'):format(share)
      image.attributes.height = nil
    end
    line:insert(image)
  end
  return pandoc.Plain(line)
end

local function opened(blocks)
  local content = pandoc.Blocks{}
  for _, block in ipairs(blocks) do
    if block.t == 'Figure' then
      content:extend(opened(block.content))
      content:extend(caption_blocks(block.caption))
    elseif block.t == 'Div' then
      local row = side_by_side(block)
      block.content = row and pandoc.Blocks{ row } or opened(block.content)
      content:insert(block)
    else
      content:insert(block)
    end
  end
  return content
end

local function unnest(fig)
  fig.content = opened(fig.content)
  return fig
end

-- The table, and an id a div around it holds: the table's own, which
-- Table above moved there for want of a caption.
local function only_table(fig)
  local tables, other, id = {}, 0, ''
  for _, block in ipairs(fig.content) do
    -- The table-wrapper div the HTML gets, or any div holding one block.
    while block.t == 'Div' and #block.content == 1 do
      if id == '' then id = block.identifier end
      block = block.content[1]
    end
    if block.t == 'Table' then
      tables[#tables + 1] = block
    elseif not (block.t == 'Plain' and #block.content == 0) then
      other = other + 1
    end
  end
  if #tables ~= 1 or other > 0 then return nil end
  return tables[1], id
end

-- A footnote in a figure's caption (11), whose mark LaTeX numbered as
-- often as it set the caption, and a tagged PDF's figure caption is set
-- twice (latexbuild's PDF_MACROS): the caption opens with
-- \OERCaptionNotes and a number of its own, and the caption the list of
-- figures takes, which the writer makes of the caption without its notes,
-- is given, without it too.
local caption_notes = 0

local function numbered_notes(fig)
  local long, held = caption_blocks(fig.caption), false
  long:walk({ Note = function() held = true end })
  if not held then return fig end
  caption_notes = caption_notes + 1
  local caption = fig.caption
  if not caption.short or #caption.short == 0 then
    caption.short = pandoc.utils.blocks_to_inlines(long):walk({
      Note = function() return {} end })
  end
  local mark = pandoc.RawInline('latex', '\\OERCaptionNotes{' .. caption_notes .. '}')
  if long[1].t == 'Plain' or long[1].t == 'Para' then
    long[1].content:insert(1, mark)
  else
    long:insert(1, pandoc.Plain({ mark }))
  end
  caption.long = long
  fig.caption = caption
  return fig
end

function Figure(fig)
  local cell = in_cell(fig)
  fig = unnest(fig)
  local tbl, id = only_table(fig)
  if tbl and #caption_blocks(tbl.caption) == 0 and #caption_blocks(fig.caption) > 0 then
    tbl.caption = fig.caption
    if tbl.identifier == '' then
      tbl.identifier = id ~= '' and id or fig.identifier
    end
    if cell then tbl.attributes[IN_CELL] = '1' end
    return tbl
  end
  local unlabeled = not cell and (own_label(fig.caption, FIGURE_WORDS) or unnumbered(fig))
  fig = numbered_notes(fig)
  if unlabeled then
    return without_label({ fig })
  end
  return fig
end

-- A line break with no line before it to end: at the start of a
-- paragraph, or right after a display formula, which ends its own line.
-- LaTeX stops on either ("There's no line here to end"); the page loses
-- nothing without it. GIAM ends every proof with one after its last
-- formula (\newline before "Q.E.D." in its proof environment).
local function no_line_to_end(inlines)
  local out, removed = pandoc.Inlines{}, false
  local after_line = false        -- something before on this line
  for _, inline in ipairs(inlines) do
    if inline.t == 'LineBreak' then
      if after_line then
        out:insert(inline)
        after_line = false
      else
        removed = true
      end
    elseif inline.t == 'Math' and inline.mathtype == 'DisplayMath' then
      out:insert(inline)
      after_line = false
    elseif inline.t == 'Space' or inline.t == 'SoftBreak' then
      out:insert(inline)
    else
      out:insert(inline)
      after_line = true
    end
  end
  return removed and out or nil
end

local function line_breaks(block)
  local inlines = no_line_to_end(block.content)
  if inlines then
    block.content = inlines
    return block
  end
  return nil
end

-- A display formula inside emphasis or another inline wrapper, which a
-- LaTeX source gives as \emph{\[ ... \]} (GIAM states every theorem so):
-- tagging leaves the paragraph's content in the section's structure
-- itself, and veraPDF's PDF/UA-2 profile fails "Sect shall not contain
-- content items" (measured: two lines in a section are enough). The
-- formula comes out of the wrapper, which keeps what's on either side.
local WRAPPERS = { Emph = true, Strong = true, Underline = true,
  Strikeout = true, SmallCaps = true, Span = true }

local function lift_display(inlines)
  local out, changed = pandoc.Inlines{}, false
  for _, inline in ipairs(inlines) do
    local holds = false
    if WRAPPERS[inline.t] then
      for _, inner in ipairs(inline.content) do
        if inner.t == 'Math' and inner.mathtype == 'DisplayMath' then
          holds = true
          break
        end
      end
    end
    if holds then
      changed = true
      local part = pandoc.Inlines{}
      local function flush()
        if #part > 0 then
          local copy = inline:clone()
          copy.content = part
          out:insert(copy)
          part = pandoc.Inlines{}
        end
      end
      for _, inner in ipairs(inline.content) do
        if inner.t == 'Math' and inner.mathtype == 'DisplayMath' then
          flush()
          out:insert(inner)
        else
          part:insert(inner)
        end
      end
      flush()
    else
      out:insert(inline)
    end
  end
  return changed and out or nil
end

-- A display formula that is a math environment of its own the writer
-- doesn't know is one: it writes an align or an eqnarray as it is, and
-- wraps anything else in \[ \] (isMathEnv, Writers/LaTeX.hs, 3.12), and
-- eqnarray* isn't in its list, so LaTeX stopped on \[\begin{eqnarray*}
-- ("Missing \endgroup inserted"; OpenIntro Statistics). Written as it is.
--
-- And amsbsy's \pmb, the poor man's bold, as unicode-math's bold italic,
-- \symbfit, whose letters the fonts have: \pmb{\hat{p}_1 - b} stopped
-- LuaTeX while LaTeX's tagging took the formula's MathML ("(nodes):
-- trying to set an attribute fails, case 2"; OpenIntro Statistics's
-- headings of its boxes), where \pmb{\hat{p}_1} and \pmb{p_1 - b} didn't.
--
-- And an mtable's empty last row, which texmath writes, where the mtable
-- has one column, as an empty line before the matrix's end, OpenStax
-- placing what's beside it so: an evaluation bar's limits (an mtable under
-- the bar and one over it, a row of each empty), and a synthetic
-- division's rows. TeX reads the empty line as \par, at which LaTeX's
-- tagging, reading a display formula's body as an argument, stopped
-- ("Paragraph ended before \environment equation* was complete": Calculus
-- Volume 2's chapter 3, Precalculus 2e's chapter 7); and in a formula in
-- text, where LaTeX read on, the row was lost, since a \\ before a
-- matrix's end makes no row, so the bar's upper limit sat low. The empty
-- line is an empty group, {}, which makes the row; another empty line,
-- which texmath doesn't write, is the line end TeX would read.
local function Math(math)
  local text = math.text:gsub('\\pmb%f[^%a]', '\\symbfit')
    :gsub('\n%s*\n(%s*\\end%s*{)', '\n{}\n%1'):gsub('\n%s*\n', '\n')
  if math.mathtype == 'DisplayMath' and text:match('^%s*\\begin%s*{eqnarray%*}') then
    return pandoc.RawInline('latex', text)
  end
  if text ~= math.text then
    math.text = text
    return math
  end
end

-- What a LaTeX book's headings hold. A label in a heading's own braces,
-- \subsection{Spread\label{sec:spread}}, is an empty span in it, which the
-- writer writes as \hypertarget, a moving argument's anchor, where its own
-- internal links are \hyperref, which finds only a \label (Writers/LaTeX.hs,
-- 3.12): "Hyper reference undefined", and a link to it that goes nowhere.
-- The span goes after the heading, which the writer writes as a \label. And
-- a link in a heading, \section{\nameref{...}} (OpenIntro Statistics's
-- appendix of data sets), goes with the heading's text to the running head,
-- which the book class sets in capitals, \MakeUppercase taking the link's
-- label with it ("PAGE-CH_DISTRIBUTIONS--CH_DISTRIBUTIONS undefined"), and to
-- the contents: the heading keeps the link's text.
local function heading(header)
  local labels, links = pandoc.Inlines{}, false
  header.content = header.content:walk({
    Span = function(span)
      if span.identifier ~= "" and #span.content == 0 then
        labels:insert(pandoc.Span({}, {id = span.identifier}))
        return {}
      end
    end,
    Link = function(link)
      links = true
      return link.content
    end,
  })
  if #labels > 0 then
    return {header, pandoc.Plain(labels)}
  end
  if links then
    return header
  end
end

-- 16. A heading inside a list, a quotation, a table, a figure, or a note,
-- which the writer makes a sectioning command where it stands: \paragraph
-- in an \item, as OpenStax puts a note with a title in a list's item. LaTeX's
-- tagging can't close the section it opens inside the environment ("The
-- structure Sect can not be closed"), so every section after it was tagged
-- inside the list, which PDF/UA-2 fails (an L holds no Sect, an LBody no
-- LI): 27 sections of Principles of Marketing. It's set as a paragraph
-- tagged as the heading it is, H1 to H6 by its level, as LaTeX's tagging
-- tags a chapter H1, bold and kept with what follows (\nobreak, since
-- longtable makes \nopagebreak its own, which stopped LaTeX in a cell), its
-- id an anchor; the contents and the bookmarks don't list it, as they'd
-- list a section. In a footnote it's a paragraph tagged as any other is,
-- since a PDF's footnote holds no heading (ISO/TS 32005, which veraPDF
-- reports as FENote-Hn). Untagged, it's the same bold paragraph.
local function heading_paragraph(header, tagged)
  local inlines = pandoc.Inlines({ pandoc.RawInline('latex', '{'
    .. (tagged and tagging_setup('para/tag=H' .. math.min(header.level, 6)) or '')
    .. '\\noindent') })
  if header.identifier ~= '' then
    inlines:insert(pandoc.Span({}, {id = header.identifier}))
  end
  inlines:insert(pandoc.RawInline('latex', '\\textbf{'))
  inlines:extend(header.content)
  inlines:insert(pandoc.RawInline('latex', '}\\par\\nobreak}'))
  return pandoc.Para(inlines)
end

-- A footnote's are made first, since Pandoc's filter visits every inline
-- element, a Note among them, before any block.
local function headings_in_note(note)
  return note:walk({ Header = function(header) return heading_paragraph(header, false) end })
end

local function headings_inside(element)
  return element:walk({ Header = function(header) return heading_paragraph(header, true) end })
end

-- A display formula a LaTeX book numbers (latexsource.resolve_counters):
-- its TeX holds each row's number as a \tag, which LaTeX sets, so the
-- numbers set beside it for the pages go. Its labels stay in its TeX, for a
-- reference inside a formula (\text{by \eqref{eq:def}}), whose key the
-- assembly doesn't prefix; the anchors before it, which it does, are the
-- targets of the links. What subequations held is put back in it, as a
-- formula still, so a theorem's emphasis gives it up as it gives up any
-- display formula (lift_display): the reader keeps only its content, which
-- the writer wraps in \[ \] unless it begins with an environment the writer
-- knows (isMathEnv, Writers/LaTeX.hs, 3.12), and amsmath stopped on an align
-- inside that ("Erroneous nesting of equation structures"). An eqnarray
-- takes no \tag ("\tag not allowed here"), so its count is set before it,
-- with the number's form, as the pages count, and the form put back after.
local function equation(span)
  if not span.classes:includes('equation') then
    return nil
  end
  local counter = span.attributes['eqnarray-counter']
  local prefix = span.attributes['eqnarray-prefix']
  local out = pandoc.Inlines{}
  for _, inner in ipairs(span.content) do
    if inner.t == 'Span' and inner.classes:includes('equation-number') then
      -- set by LaTeX
    elseif inner.t == 'Math' then
      if span.classes:includes('subequations') then
        inner.text = '\\begin{subequations}' .. inner.text .. '\\end{subequations}'
      end
      if counter and prefix and counter:match('^%d+$') and prefix:match('^[%w.%-]*$') then
        out:insert(pandoc.RawInline('latex', '\\global\\let\\oerTheEquation\\theequation'
          .. '\\gdef\\theequation{' .. prefix .. '\\arabic{equation}}'
          .. '\\setcounter{equation}{' .. counter .. '}'))
        out:insert(inner)
        out:insert(pandoc.RawInline('latex', '\\global\\let\\theequation\\oerTheEquation{}'))
      else
        out:insert(inner)
      end
    else
      out:insert(inner)
    end
  end
  return out
end

-- 8. A language tag the PDF can carry: BCP 47's letters, digits, and
-- hyphens, nothing a PDF string would read otherwise.
local function language(attr)
  local lang = attr.attributes.lang
  if lang and lang:match('^%a%a?%a?%a?%a?%a?%a?%a?[%-%w]*$') and not lang:match('%-%-')
      and not lang:match('%-$') then
    return lang
  end
end

local function marked(lang, inlines)
  local out = pandoc.Inlines({ pandoc.RawInline('latex', '\\oerlang{' .. lang .. '}{') })
  out:extend(inlines)
  out:insert(pandoc.RawInline('latex', '}'))
  return out
end

-- A span or a link in another language, its attribute kept for babel.
local function inline_language(element)
  local lang = language(element.attr)
  if lang then
    return marked(lang, { element })
  end
end

local function holds_heading(blocks)
  for _, block in ipairs(blocks) do
    if block.t == 'Header' or (block.t == 'Div' and holds_heading(block.content)) then
      return true
    end
  end
  return false
end

-- A div's blocks in its language: all in one environment, or, where they
-- hold a heading, the blocks between headings in one each, so the latex
-- target's passage reads as one, the heading's words marked, a div inside
-- in a language of its own left to that.
local function in_language(blocks, lang)
  local opening = pandoc.RawBlock('latex', '\\begin{oerlanguage}{' .. lang .. '}')
  local closing = pandoc.RawBlock('latex', '\\end{oerlanguage}')
  local out, run = pandoc.Blocks({}), pandoc.Blocks({})
  local function flush()
    if #run > 0 then
      out:insert(opening)
      out:extend(run)
      out:insert(closing)
      run = pandoc.Blocks({})
    end
  end
  if not holds_heading(blocks) then
    run = blocks
    flush()
    return out
  end
  for _, block in ipairs(blocks) do
    if block.t == 'Header' then
      flush()
      if #block.content > 0 then
        block.content = marked(lang, block.content)
      end
      out:insert(block)
    elseif block.t == 'Div' and language(block.attr) then
      flush()
      out:insert(block)
    elseif block.t == 'Div' and holds_heading(block.content) then
      flush()
      block.content = in_language(block.content, lang)
      out:insert(block)
    else
      run:insert(block)
    end
  end
  flush()
  return out
end

local function div_language(div)
  local lang = language(div.attr)
  if lang then
    div.content = in_language(div.content, lang)
    return div
  end
end

local function term_notes(list)
  local items, moved_any = pandoc.List({}), false
  for _, item in ipairs(list.content) do
    local moved = pandoc.Inlines({})
    local term = pandoc.Inlines(item[1]):walk({
      Note = function(note)
        moved:insert(note)
        return {}
      end,
    })
    local definitions = pandoc.List(item[2])
    if #moved > 0 then
      moved_any = true
      local blocks = pandoc.Blocks(definitions[1] or {})
      local first = blocks[1]
      if first and (first.t == 'Para' or first.t == 'Plain') then
        local content = pandoc.Inlines({})
        content:extend(moved)
        content:extend(first.content)
        first.content = content
        blocks[1] = first
      else
        blocks:insert(1, pandoc.Plain(moved))
      end
      definitions[1] = blocks
    end
    items:insert({ term, definitions })
  end
  if moved_any then
    list.content = items
    return list
  end
end

-- A box, a div of class box (a LibreTexts page's Example, Exercise, or
-- Note; a LaTeX book's passage in a frame), which the pages and the EPUB
-- draw with a border: set off by a rule above and one below, artifacts
-- (\OERBoxRule), so where it ends shows too.
local function box_rules(div)
  if not div.classes:includes('box') then return nil end
  return {
    pandoc.RawBlock('latex', '\\OERBoxRule{above}'),
    div,
    pandoc.RawBlock('latex', '\\OERBoxRule{below}'),
  }
end

-- A fill-in blank, a run of four or more underscores in the text (Sociology's
-- quiz asks "Core nations are also known as __________________"): the
-- writer's \_ each, in \OERBlank, which marks them, so that PDF_MACROS
-- can draw a blank that runs past the end of its line shorter, to end
-- where the line does, and tags each a Span whose ActualText is "blank".
-- A run of three or fewer is never drawn shorter, so it isn't marked.
-- Last, so the text the other passes read (a link's
-- /Contents) has the underscores. Not in a link's text, an image's
-- description, a heading, or the metadata, whose plain text the writer
-- takes as well (a bare address's \url, alt=, a bookmark's
-- \texorpdfstring, pdftitle), and where the mark, raw LaTeX, would leave
-- the underscores out. Nor in what lua-ul draws a line under or through
-- or a highlight behind (\ul, \st, \hl), which it draws as the line is
-- made, before the blank could be drawn shorter: the line would still
-- run past the margin.
local function blanks(str)
  if not str.text:find('____', 1, true) then return nil end
  local out, rest = pandoc.Inlines{}, str.text
  while true do
    local first, last = rest:find('____+')
    if not first then break end
    if first > 1 then out:insert(pandoc.Str(rest:sub(1, first - 1))) end
    out:insert(pandoc.RawInline('latex',
      '\\OERBlank{' .. ('\\_'):rep(last - first + 1) .. '}'))
    rest = rest:sub(last + 1)
  end
  if rest ~= '' then out:insert(pandoc.Str(rest)) end
  return out
end

-- A formula FIT_MACROS fits (19): a display formula the writer wraps in
-- \[ \], which TeX never breaks, but not one it writes as an environment
-- of its own (isMathEnv, Writers/LaTeX.hs, 3.12.1: align, gather, and the
-- rest), whose list TeX makes a cell at a time; and a formula in text that
-- is an environment, an array or a matrix, which TeX can't break either,
-- as the worked examples' steps in OpenStax's math books are. Not one in a
-- table, whose table is fitted; nor in a heading, a caption, a link, or a
-- picture's description, which LaTeX sets more than once or not as text.
local WHOLE_MATH = {
  align = true, flalign = true, alignat = true, dmath = true, dgroup = true,
  darray = true, gather = true, multline = true, subequations = true,
  equation = true, eqnarray = true, displaymath = true,
}

local function environment(text)
  local name = text:match('^%s*\\begin%s*{([^}]*)}')
  if not name then return nil end
  local closing = text:match('\\end%s*{([^}]*)}%s*$')
  return name, closing == name
end

local function fit_math(math_)
  local name, whole = environment(math_.text)
  local kind
  if math_.mathtype == 'DisplayMath' then
    if name and WHOLE_MATH[name:gsub('%*$', '')] then return nil end
    -- A numbered display (\tag, as equation() writes a book's number) is
    -- e, which FIT_MACROS doesn't center: centered, its number was set at
    -- the end of a line as wide as the margins allow.
    kind = math_.text:find('\\tag', 1, true) and 'e' or 'd'
  elseif name and whole then
    kind = 'i'
  else
    return nil
  end
  return { pandoc.RawInline('latex', '{\\OERFitFormula{' .. next_fit() .. '}{' .. kind .. '}'),
           math_, pandoc.RawInline('latex', '}') }
end

local function fit_formulas(doc)
  local skip = function(element) return element, false end
  doc.blocks = doc.blocks:walk{
    traverse = 'topdown', Table = skip, Header = skip, Figure = skip, Link = skip,
    Image = skip, Math = fit_math }
  return doc
end

return {
  { BulletList = headings_inside, OrderedList = headings_inside,
    DefinitionList = headings_inside, BlockQuote = headings_inside,
    Table = headings_inside, Figure = headings_inside, Note = headings_in_note },
  { DefinitionList = term_notes },
  { Span = equation },
  { Inlines = lift_display, Header = heading },
  { Table = mark_in_cells },
  { Figure = Figure },
  { Para = line_breaks, Plain = line_breaks },
  { Table = Table, Image = Image, Link = Link, Math = Math },
  { Div = box_rules },
  { Span = inline_language, Link = inline_language, Div = div_language },
  { Pandoc = function(doc)
      local skip = function(element) return element, false end
      doc.blocks = doc.blocks:walk{
        traverse = 'topdown', Image = skip, Header = skip, Link = skip,
        Underline = skip, Strikeout = skip,
        Span = function(span) if span.classes:includes('mark') then return span, false end end,
        Str = blanks }
      return doc
    end },
  { Pandoc = fit_formulas },
}
