--[[
markdown-html.lua

Runs when a Markdown source is read, and gives the raw HTML in it the
treatment an HTML source's HTML gets, so that a Markdown book and an HTML
book come out the same.

Pandoc's Markdown reader keeps raw HTML one tag at a time: x<sup>2</sup>
arrives as a raw "<sup>", the text "2", and a raw "</sup>"; a table
written in HTML as a raw "<table>", a raw "<tr>", a raw "<td align=...>"
with its contents parsed as Markdown, and so on. Left like that, a
reader of the output gets whatever the tags were (an align attribute
that XHTML forbids, 99 of them in one book's EPUB) and none of it is a
Pandoc element: an <img> the media gate can't see, a table the header
pre-pass can't reach, a superscript that is only a superscript in HTML.

So, in each list of blocks and of inlines, an opening tag and its
matching closing tag are put back together with what lies between them
(written as HTML), and the whole is read with Pandoc's HTML reader; a
tag that stands alone (<br>, <img>, <hr>) is read the same way. What
comes back is cleaned by html-raw.lua and html-source.lua, loaded from
their own files, so there is one set of rules. An unmatched tag is left
for html-raw.lua, which drops it and keeps what it wrapped, as it does
for an HTML source.

A raw <pre> the Markdown reader keeps whole, as it does one that opens a
block, is read the same way, a CodeBlock: kept as raw HTML, it was in
the pages and the EPUB and nowhere else, gone from a PDF. A raw <code>,
<kbd>, <samp>, <var>, or <tt> comes here read already, as written, by
markdown-reader.lua; one it leaves to Pandoc's reader, over more than a
line, say, is read as HTML like the rest, its text as Markdown read it,
so that it's code in a PDF too, where its tags were dropped.

Never touched: code, which is a Code or CodeBlock element and holds no
raw HTML to find; a <pre> in pieces, and a raw <script>, <style>,
<textarea>, or <math>, whose contents are verbatim; and comments, which
the filter drops. Nor is anything outside raw HTML changed, except an
href on a <span> or <div> (RDFa, usually), which the Markdown reader
made an attribute and XHTML allows on neither.

Copyright 2026 Robert Szarka

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
]]

local HERE = PANDOC_SCRIPT_FILE:match('^(.*)[/\\]') or '.'

-- A filter file's handlers, loaded into a table of their own.
local function handlers(name, wanted)
  local env = setmetatable({}, { __index = _G })
  local chunk = assert(loadfile(HERE .. '/' .. name, 't', env))
  chunk()
  local out = {}
  for _, key in ipairs(wanted) do
    if env[key] then out[key] = env[key] end
  end
  return out
end

local RAW = handlers('html-raw.lua', { 'RawInline', 'RawBlock', 'Blocks' })
local SOURCE = handlers('html-source.lua', { 'Table', 'Div', 'Span', 'Header',
                                            'Image', 'Link' })

local VOID = { area = true, br = true, col = true, embed = true, hr = true,
               img = true, input = true, source = true, track = true,
               wbr = true }
local VERBATIM = { pre = true, script = true, style = true, math = true,
                   textarea = true }
local reread = 0

-- The tag a raw fragment opens or closes: (name, closing?, self-closed?)
local function tag_of(el)
  if el.format ~= 'html' then return nil end
  local text = el.text
  if text:match('^%s*<!') then return nil end            -- comment, doctype
  local slash, name = text:match('^%s*<(/?)%s*([%w:-]+)')
  if not name then return nil end
  name = name:lower()
  local whole = text:lower():match('^%s*<.-</%s*' .. name .. '%s*>%s*$') ~= nil
  return name, slash == '/', text:match('/%s*>%s*$') ~= nil or whole
end

local function is_raw(el)
  return el.t == 'RawInline' or el.t == 'RawBlock'
end

local function clean(doc)
  doc = doc:walk(RAW)
  return doc:walk(SOURCE)
end

-- Read html as blocks, or as inlines when the list is one of inlines.
local function read_html(html, inline)
  local doc = clean(pandoc.read(html, 'html+raw_html+epub_html_exts'))
  reread = reread + 1
  if not inline then return doc.blocks end
  local out = pandoc.Inlines({})
  for i, block in ipairs(doc.blocks) do
    if block.t == 'Para' or block.t == 'Plain' then
      if i > 1 then out:insert(pandoc.Space()) end
      out:extend(block.content)
    else
      return nil                     -- a block where an inline was: leave it
    end
  end
  return out
end

local function as_html(list, inline)
  local blocks = inline and { pandoc.Plain(list) } or list
  return pandoc.write(pandoc.Pandoc(blocks), 'html')
end

-- A whole <pre> as a code block, its text inside a <code> where it has
-- none: the HTML reader makes one without a <code> paragraphs in the
-- text's face, its spaces no-break spaces, since 3.11 (#11810), and a code
-- block in 3.9, TI's minimum (PANDOC-NOTES, the HTML reader), where the
-- raw <pre> the pages had shown was set as code. The start tag ends at a
-- '>' outside quotes (<pre data-prompt=">>>">), and a line end right after
-- it, which HTML drops from a <pre>, is dropped: inside a <code> it would
-- be the code's first line, blank, and before a <code> the HTML reader
-- takes it for the <pre>'s text, and the <code> for inline code (a review
-- of Round 35).
local function code_pre(text)
  local quote, open_end = nil, nil
  for p = 1, #text do
    local c = text:sub(p, p)
    if quote then
      if c == quote then quote = nil end
    elseif c == '"' or c == "'" then
      quote = c
    elseif c == '>' then
      open_end = p
      break
    end
  end
  local close = text:lower():match('.*()</%s*pre')
  if not open_end or not close or close <= open_end then return text end
  local inner = text:sub(open_end + 1, close - 1):gsub('^\r?\n', '', 1)
  if inner:lower():match('^<code[%s>]') then
    return text:sub(1, open_end) .. inner .. text:sub(close)
  end
  return text:sub(1, open_end) .. '<code>' .. inner .. '</code>' .. text:sub(close)
end

local function whole_pre(el)
  local name, closing, alone = tag_of(el)
  return name == 'pre' and not closing and alone
end

-- list ready to go through HTML: a whole <pre> in it given its <code>
-- (code_pre).
local function for_html(list, inline)
  local filter = {
    RawBlock = function(raw)
      if whole_pre(raw) then return pandoc.RawBlock('html', code_pre(raw.text)) end
    end,
  }
  return inline and pandoc.Inlines(list):walk(filter) or pandoc.Blocks(list):walk(filter)
end

local function balance(list, inline)
  local out = inline and pandoc.Inlines({}) or pandoc.Blocks({})
  local i, changed = 1, false
  while i <= #list do
    local el = list[i]
    local name, closing, alone = nil, nil, nil
    if is_raw(el) then name, closing, alone = tag_of(el) end
    local done = false
    local pre = not inline and is_raw(el) and whole_pre(el)
    if name and not closing and (not VERBATIM[name] or pre) then
      if alone or VOID[name] then
        local new = read_html(pre and code_pre(el.text) or el.text, inline)
        if new then out:extend(new); done, changed = true, true end
      else
        local depth, j = 1, i + 1
        while j <= #list do
          if is_raw(list[j]) then
            local other, shut = tag_of(list[j])
            if other == name and shut then depth = depth - 1
            elseif other == name then depth = depth + 1 end
            if depth == 0 then break end
          end
          j = j + 1
        end
        if j <= #list then
          local middle = {}
          local raw_inside = false
          for k = i + 1, j - 1 do
            middle[#middle + 1] = list[k]
            if is_raw(list[k]) then raw_inside = true end
          end
          -- A div around blocks Pandoc read itself, as a table in its
          -- wrapper: the div from its tags alone, the blocks as they are.
          -- Through HTML and back, a table there can lose its columns
          -- (GIAM's table of a statement and its contrapositive, read back
          -- from AsciiDoc: 6 columns became 2).
          if name == 'div' and not inline and not raw_inside then
            local shell = read_html(el.text .. list[j].text, false)
            if shell and #shell == 1 and shell[1].t == 'Div' then
              shell[1].content = pandoc.Blocks(middle)
              out:insert(shell[1])
              i, done, changed = j, true, true
            end
          end
        end
        if not done and j <= #list then
          local middle = {}
          for k = i + 1, j - 1 do middle[#middle + 1] = list[k] end
          middle = for_html(middle, inline)
          local html = el.text .. as_html(middle, inline) .. list[j].text
          local new = read_html(html, inline)
          if new then
            out:extend(new)
            i, done, changed = j, true, true
          end
        end
      end
    end
    if not done then out:insert(el) end
    i = i + 1
  end
  return changed and out or nil
end

function Inlines(list) return balance(list, true) end
function Blocks(list) return balance(list, false) end

-- RDFa on a span or div: the Markdown reader makes it an attribute.
function Span(span)
  if span.attributes.href then span.attributes.href = nil; return span end
end

function Div(div)
  if div.attributes.href then div.attributes.href = nil; return div end
end

function Pandoc(doc)
  if reread > 0 then
    io.stderr:write(('[markdown-html] %s: %d raw HTML element(s) read as '
      .. 'HTML\n'):format(PANDOC_STATE.input_files[1] or '-', reread))
  end
  return nil
end
