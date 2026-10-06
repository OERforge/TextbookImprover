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

return {
  { Figure = Figure },
  { Para = line_breaks, Plain = line_breaks },
  { Table = Table, Image = Image, Link = Link },
}
