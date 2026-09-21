--[[
html-raw.lua

Runs when an HTML page is read with raw_html on, which is how every HTML
page is read here: with it off, Pandoc's reader fetches each <iframe>
over the network to read what it framed into the page (Readers/HTML.hs,
pIframe). The price is that every tag the reader has no element for
arrives as a fragment of raw markup. This filter deals with those, and
does nothing else, so it can run on a page a person finished as well as
on a source:

  - Raw HTML goes. raw_html is on so that the reader fetches nothing
    (see convert.py), and the price is that every tag the reader has no
    element for arrives as a fragment of markup: <footer>, </footer>,
    <nav epub:type="toc">, and a stray </code> the author never opened,
    which the writers pass through and which made an EPUB that was not
    well-formed. Dropping the fragment keeps what was between the tags,
    which is what the reader does with raw_html off. An <iframe> becomes
    an "embed": a Div (a Span, inline) with class embed that carries the
    iframe's attributes and holds a link to what it framed, named by its
    title. target-blocks.lua decides at render time: an HTML target gets
    the <iframe> back, the EPUB and anything else the link, since a
    reading system can't be relied on to load a remote frame. A frame
    with no title is given one, which WCAG 4.1.2 wants of it anyway.
    What was dropped is counted on stderr, by tag.

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

local dropped = {}

local function raw_tag(text)
  return text:match('^%s*<%s*/?%s*([%w:-]+)')
end

local function unescape(value)
  return (value:gsub('&quot;', '"'):gsub('&#39;', "'"):gsub('&lt;', '<')
                :gsub('&gt;', '>'):gsub('&amp;', '&'))
end

-- The attributes of an opening tag, in order, as pairs. A bare attribute
-- (allowfullscreen) has its own name as its value.
local function tag_attributes(text)
  local body = text:match('^%s*<%s*[%w:-]+(.-)/?>%s*$') or ''
  local pairs_ = {}
  local rest = body
  while true do
    local name, after = rest:match('^%s*([%w:_.-]+)()')
    if name == nil then break end
    rest = rest:sub(after)
    local value
    local quoted, after2 = rest:match('^%s*=%s*"([^"]*)"()')
    if quoted == nil then quoted, after2 = rest:match("^%s*=%s*'([^']*)'()") end
    if quoted == nil then quoted, after2 = rest:match('^%s*=%s*([^%s>]+)()') end
    if quoted then value, rest = unescape(quoted), rest:sub(after2)
    else value = name end
    pairs_[#pairs_ + 1] = { name:lower(), value }
  end
  return pairs_
end

local function framed(text, block)
  local attributes, src, title = tag_attributes(text), nil, nil
  for _, pair in ipairs(attributes) do
    if pair[1] == 'src' then src = pair[2] end
    if pair[1] == 'title' then title = pair[2] end
  end
  if src == nil or src == '' then return nil end
  if title == nil or title == '' then
    title = 'Embedded content at ' .. (src:match('^%a*:?//([^/?#]+)') or src)
    attributes[#attributes + 1] = { 'title', title }
  end
  local attr = pandoc.Attr('', { 'embed' }, attributes)
  local link = pandoc.Link(title, src)
  if block then return pandoc.Div({ pandoc.Para({ link }) }, attr) end
  return pandoc.Span({ link }, attr)
end

-- Kept as they are: tags the reader has no element for that are valid
-- in HTML and in an EPUB's XHTML and mean something. <details> and
-- <summary> are how a book hides an answer until it's asked for;
-- dropped, the answer sat open on the page.
local KEEP = { details = true, summary = true }

local function raw_html(el, block)
  if el.format ~= 'html' then return nil end
  local tag = (raw_tag(el.text) or ''):lower()
  if KEEP[tag] then return nil end
  if tag == 'iframe' and not el.text:match('^%s*</') then
    local embed = framed(el.text, block)
    if embed then return embed end
  end
  if tag ~= '' then dropped[tag] = (dropped[tag] or 0) + 1 end
  return {}
end

function RawInline(el) return raw_html(el, false) end
function RawBlock(el) return raw_html(el, true) end

-- A <summary> may hold phrasing content only, and both readers make its
-- text a paragraph: <summary><p>Answer</p></summary>. A paragraph alone
-- between the tags is plain text again.
local function raw_is(block, pattern)
  return block and block.t == 'RawBlock' and block.format == 'html'
    and block.text:lower():match(pattern) ~= nil
end

function Blocks(blocks)
  local changed = false
  for i = 2, #blocks - 1 do
    if blocks[i].t == 'Para' and raw_is(blocks[i - 1], '^%s*<summary[%s>]')
        and raw_is(blocks[i + 1], '^%s*</summary') then
      blocks[i] = pandoc.Plain(blocks[i].content)
      changed = true
    end
  end
  return changed and blocks or nil
end

local function report_dropped()
  local names = {}
  for tag in pairs(dropped) do names[#names + 1] = tag end
  if #names == 0 then return end
  table.sort(names)
  local parts = {}
  for _, tag in ipairs(names) do
    parts[#parts + 1] = ('%s x%d'):format(tag, dropped[tag])
  end
  io.stderr:write(('[html-raw] %s: raw tags dropped, their contents kept: %s\n')
    :format(PANDOC_STATE.input_files[1] or '-', table.concat(parts, ', ')))
end


function Pandoc(doc)
  report_dropped()
  return nil
end
