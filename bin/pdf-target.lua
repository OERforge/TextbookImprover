-- pdf-target.lua -- what Pandoc's LaTeX writer can't be told, for a
-- tagged PDF. Run by build-pdf.py on the assembled book, after
-- target-blocks.lua; the header it relies on (\OERLinkContents, the
-- artifact key) is written by build-pdf.py too.
--
-- Three things, each because the writer has no way to express it
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

function Table(tbl)
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

return {
  { Table = Table, Image = Image, Link = Link },
}
