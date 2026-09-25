-- NOT YET WIRED IN. Kept here as the reference for the marker vocabulary
-- Markdown input has to accept (on the roadmap then): it is the filter the
-- textbook this project was built alongside is written with, and its
-- `::: matrix` div is what `tables.markers` will default to.
--
-- The pipeline reaches the same output by a different road. Here the
-- declaration is in the document and the filter reads it; in the
-- pipeline the declaration is in table-headers.csv and the pre-pass
-- resolves it, because a .docx has nowhere to put one. Both then do the
-- same two jobs, and this file is the shorter statement of them: set
-- row_head_columns so the writer emits <th>, and set scope, which the
-- writer does not.
--
-- Two things it does that the pipeline does not yet. It brackets each
-- table with \tagpdfsetup{table/header-columns={1}} for the PDF, which
-- is the LaTeX half of the roadmap's PDF work. And it defaults every unmarked
-- table to a header row, which is right for a book whose tables all have
-- one and wrong in general; the pipeline guesses instead, and where it
-- has no answer a declared setting decides.
--
--[[
matrix-headers.lua — pandoc Lua filter for table headers in HTML and PDF.

Two jobs:

1. Every table: mark the cells of the table head with scope="col" so that
   HTML output gets <th scope="col">. Pandoc already emits <th> there; the
   scope makes the association explicit.

2. Tables inside a ::: matrix ::: div: additionally treat the first column
   as row headers. In HTML this produces <th scope="row"> for the first cell
   of each body row. Pandoc's LaTeX writer ignores row_head_columns, so for
   the PDF build the filter instead brackets the table with
   \tagpdfsetup{table/header-columns={1}} ... {} so that latex-lab tags the
   first column as TH and resets the setting afterwards.

The header *row* needs no LaTeX setting: pandoc always emits longtable with
\endfirsthead/\endhead, and latex-lab uses those rows as the header
automatically (and ignores table/header-rows when it does).

Usage:
  pandoc textbook.md -L matrix-headers.lua ...

Markdown:
  ::: matrix
  |      | Left  | Right |
  |------|-------|-------|
  | Up   | 1, 5  | 3, 7  |
  | Down | 2, 10 | 4, 6  |
  :::
--]]

local ROW_HEAD_COLUMNS = 1

local function set_scope(cell, value)
  local a = cell.attr
  a.attributes["scope"] = value
  cell.attr = a
end

-- scope="col" on the table head, for every table.
function Table(tbl)
  for _, row in ipairs(tbl.head.rows) do
    for _, cell in ipairs(row.cells) do
      set_scope(cell, "col")
    end
  end
  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.head) do
      for _, cell in ipairs(row.cells) do
        set_scope(cell, "col")
      end
    end
  end
  return tbl
end

local function add_row_headers(tbl)
  for _, body in ipairs(tbl.bodies) do
    body.row_head_columns = ROW_HEAD_COLUMNS
    for _, row in ipairs(body.body) do
      for i = 1, ROW_HEAD_COLUMNS do
        if row.cells[i] then set_scope(row.cells[i], "row") end
      end
    end
  end
  return tbl
end

function Div(div)
  if not div.classes:includes("matrix") then return nil end
  local walked = div:walk {
    Blocks = function(blocks)
      local out = pandoc.Blocks{}
      for _, blk in ipairs(blocks) do
        if blk.t == "Table" then
          local t = add_row_headers(blk)
          if FORMAT:match("latex") then
            out:insert(pandoc.RawBlock("latex",
              "\\tagpdfsetup{table/header-columns={" .. ROW_HEAD_COLUMNS .. "}}"))
            out:insert(t)
            out:insert(pandoc.RawBlock("latex",
              "\\tagpdfsetup{table/header-columns={}}"))
          else
            out:insert(t)
          end
        else
          out:insert(blk)
        end
      end
      return out
    end
  }
  -- Drop the wrapper div itself; it has served its purpose.
  return walked.content
end
