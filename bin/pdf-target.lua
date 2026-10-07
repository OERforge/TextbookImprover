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
--    before the table and cleared after it. Header rows need nothing:
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
--
-- 4. A table inside a table's cell. The writer makes each a longtable,
--    and LaTeX stops on a longtable inside another ("Extra alignment tab";
--    jgm/pandoc#3586). The inner table is written as its rows, one line
--    each, its cells' text side by side: GIAM's long division, a layout,
--    is the case this was measured on.
--
-- 5. An eqnarray* formula, which the writer wraps in \[ \] where it writes
--    an eqnarray as it is, and LaTeX stops on: written as it is. And \pmb,
--    on which LuaTeX stopped while the formula was tagged.
--
-- 6. A heading's label and links (below).
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

-- A quotation inside a table cell is unwrapped to what it holds: a PDF's
-- structure doesn't allow a BlockQuote in a TD (ISO/TS 32005, which veraPDF
-- reports as TD-BlockQuote). DCIC sets code side by side in a table that
-- way, five blocks of it, indented as quotations.
local unquote = {BlockQuote = function(quote) return quote.content end}

-- A cell spanning rows is set with \multirow, which LaTeX's tagging code
-- doesn't follow (the tagging project lists multirow as incompatible): it
-- tags the cell as one row's and the rows below as having an empty cell
-- of their own there. table/multirow, said inside the cell, gives it its
-- RowSpan and leaves the cells it covers untagged.
local function mark_row_span(cell)
  if (cell.row_span or 1) <= 1 then return end
  local raw = pandoc.RawInline('latex', string.format(
    '\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/multirow=%d}\\fi ', cell.row_span))
  local first = cell.contents[1]
  if first and (first.t == 'Plain' or first.t == 'Para') then
    first.content:insert(1, raw)
  else
    cell.contents:insert(1, pandoc.Plain({raw}))
  end
end

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
-- since \tagpdfsetup holds until it's changed. Tagging makes it a Table
-- inside the cell's TD, which veraPDF passes (measured, LaTeX 2026-06-01).
-- A cell spanning rows needs multirow, which isn't loaded: such a table
-- is written as lines of text, as every inner table once was.
local ALIGN = { AlignLeft = 'l', AlignCenter = 'c', AlignRight = 'r' }

local function cell_latex(cell)
  local text = pandoc.write(pandoc.Pandoc(cell.contents), 'latex')
  text = text:gsub('%s+$', ''):gsub('^%s+', ''):gsub('\n%s*\n', ' ')
  if cell.col_span > 1 then
    text = '\\multicolumn{' .. cell.col_span .. '}{c}{' .. text .. '}'
  end
  return text
end

local function as_tabular(inner)
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
  local lines = {}
  for i, row in ipairs(rows_of(inner)) do
    local cells = {}
    for _, cell in ipairs(row.cells) do
      cells[#cells + 1] = cell_latex(cell)
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
  return pandoc.RawBlock('latex',
    '{' .. (#keys > 0 and ('\\tagpdfsetup{' .. table.concat(keys, ',') .. '}') or '')
    .. '\\begin{tabular}[t]{' .. table.concat(spec) .. '}\n'
    .. table.concat(lines, '\n') .. '\n\\end{tabular}}')
end

local function flatten_nested(tbl)
  for _, row in ipairs(rows_of(tbl)) do
    for _, cell in ipairs(row.cells) do
      cell.contents = cell.contents:walk({
        Table = function(inner)
          -- The innermost first: a table in this one's cells is written
          -- before this one is.
          flatten_nested(inner)
          local tabular = as_tabular(inner)
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

function Table(tbl)
  flatten_nested(tbl)
  unquote_cells(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    unquote_cells(body.head)
    unquote_cells(body.body)
  end
  unquote_cells(tbl.foot.rows)
  local columns = 0
  for _, body in ipairs(tbl.bodies) do
    if body.row_head_columns > columns then
      columns = body.row_head_columns
    end
  end
  if columns == 0 then
    return tbl
  end
  local list = {}
  for i = 1, columns do
    list[#list + 1] = tostring(i)
  end
  return {
    pandoc.RawBlock("latex", "\\tagpdfsetup{table/header-columns={"
                    .. table.concat(list, ",") .. "}}"),
    tbl,
    pandoc.RawBlock("latex", "\\tagpdfsetup{table/header-columns={}}"),
  }
end

local function decorative(img)
  return img.attributes["aria-hidden"] == "true"
    or img.attributes["role"] == "presentation"
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
    return {
      pandoc.RawInline("latex", "{\\OERArtifactGraphics"),
      img,
      pandoc.RawInline("latex", "}"),
    }
  end
  if changed then
    return img
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
                     "\\OERLinkContents{" .. tex_escape(contents) .. "}"),
    link,
    pandoc.RawInline("latex", "\\OERLinkContentsReset{}"),
  }
end

-- Figures the writer can't make one LaTeX figure of (Writers/LaTeX.hs,
-- 3.12). A figure inside a figure is written as the inner one's content
-- with an empty \caption{} of its own before the outer one's, so the PDF
-- numbers two captions in one figure: the
-- inner figure's content stands in the outer one, and its caption, if it
-- had one, as a paragraph under it. A figure holding only a table is
-- written as the table, which can't float, and the figure's caption is
-- dropped: the caption becomes the table's, when the table has none.
local function caption_blocks(caption)
  return caption and caption.long or pandoc.Blocks{}
end

local function unnest(fig)
  local content = pandoc.Blocks{}
  for _, block in ipairs(fig.content) do
    if block.t == 'Figure' then
      content:extend(block.content)
      local long = caption_blocks(block.caption)
      if #long > 0 then
        content:extend(long)
      end
    else
      content:insert(block)
    end
  end
  fig.content = content
  return fig
end

local function only_table(fig)
  local tables, other = {}, 0
  for _, block in ipairs(fig.content) do
    -- The table-wrapper div the HTML gets, or any div holding one block.
    while block.t == 'Div' and #block.content == 1 do
      block = block.content[1]
    end
    if block.t == 'Table' then
      tables[#tables + 1] = block
    elseif not (block.t == 'Plain' and #block.content == 0) then
      other = other + 1
    end
  end
  if #tables ~= 1 or other > 0 then return nil end
  return tables[1]
end

function Figure(fig)
  fig = unnest(fig)
  local tbl = only_table(fig)
  if tbl and #caption_blocks(tbl.caption) == 0 and #caption_blocks(fig.caption) > 0 then
    tbl.caption = fig.caption
    if tbl.identifier == '' then tbl.identifier = fig.identifier end
    return tbl
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
local function Math(math)
  local text = math.text:gsub('\\pmb%f[^%a]', '\\symbfit')
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

-- A display formula a LaTeX book numbers (latexsource.resolve_counters):
-- its TeX holds each row's number as a \tag, which LaTeX sets, so the
-- numbers set beside it for the pages go. Its labels go from its TeX, the
-- anchors before it standing for them, since the assembly gives those its
-- page's prefix (page-two--eq:energy), as it gives each link to them. What
-- subequations held is put back in it: the reader keeps only its content,
-- which the writer wraps in \[ \] unless it begins with an environment the
-- writer knows (isMathEnv, Writers/LaTeX.hs, 3.12), and amsmath stopped on
-- an align inside that ("Erroneous nesting of equation structures").
local function equation(span)
  if not span.classes:includes('equation') then
    return nil
  end
  local out = pandoc.Inlines{}
  for _, inner in ipairs(span.content) do
    if inner.t == 'Span' and inner.classes:includes('equation-number') then
      -- set by LaTeX
    elseif inner.t == 'Math' then
      -- A label on a line of its own leaves the line blank, which ends
      -- the paragraph inside the environment ("Paragraph ended before
      -- \environment equation was complete"); one line end is kept, which
      -- a comment before it needs.
      local text, n = inner.text:gsub('\\label%s*(%b{})', '')
      repeat
        text, n = text:gsub('\n[ \t]*\n', '\n')
      until n == 0
      if span.classes:includes('subequations') then
        text = text:gsub('\\pmb%f[^%a]', '\\symbfit')
        out:insert(pandoc.RawInline('latex', '\\begin{subequations}' .. text
          .. '\\end{subequations}'))
      else
        inner.text = text
        out:insert(inner)
      end
    else
      out:insert(inner)
    end
  end
  return out
end

return {
  { Span = equation },
  { Inlines = lift_display, Header = heading },
  { Figure = Figure },
  { Para = line_breaks, Plain = line_breaks },
  { Table = Table, Image = Image, Link = Link, Math = Math },
}
