-- deck-html.lua -- a deck as a page. Runs at render time for an html
-- target, before target-blocks.lua, on a page whose intermediate records a
-- slide level (deck-slide-level, which decks.py sets when the deck is
-- read); any other page passes through untouched.
--
-- Three things make a deck a page:
--
-- 1. Its headings go below its title. The title is the page's H1, from the
--    deck's YAML, in the template's title block, so a section's heading
--    is an H2, one in a section an H3, and a slide's heading one below the
--    sections it's in: H2 for a slide before the deck's first section, as
--    an agenda often is, H3 for one in a section. A heading in a slide,
--    which beamer makes a block, is one below the slide's, or below the
--    slide's own heading it's under, with no level skipped whatever levels
--    the deck gives them, and so is one in its notes, a quotation, a list,
--    a table, or a figure, where Pandoc's slide writers find no section,
--    whatever its level. A deck with no title has no H1 above them, so its
--    headings start at H1. A piece the split cut from a deck has its own
--    heading for its title, and its body's headings start at H2.
--
-- 2. A pause, Pandoc's ". . ." on a line of its own, which a slide shows
--    as the slide's next step and a page would show as three dots, goes.
--
-- 3. Its speaker notes, Pandoc's ::: notes divs, go where DECK_NOTES says,
--    slides.notes in the target's settings: collapsed, under the slide's
--    content in a <details> a reader opens (the default); visible, the
--    same <details> open; or omitted. A <details> rather than an <aside>,
--    which would make every slide's notes a landmark, all with one name,
--    for a screen reader to list: a disclosure is read as a button, its
--    state said, and its content skipped while it's closed. Its summary is
--    DECK_NOTES_LABEL, slides.notes_label, in the page's own language.
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

local NOTES = os.getenv('DECK_NOTES') or 'collapsed'
local LABEL = os.getenv('DECK_NOTES_LABEL') or ''
if LABEL == '' then LABEL = 'Speaker notes' end

local function escape(text)
  return (text:gsub('&', '&amp;'):gsub('<', '&lt;'):gsub('>', '&gt;'))
end

-- A pause as the slide writers know one (isPause, Writers/HTML.hs).
local function pause(para)
  local c = para.content
  if #c == 5 and c[1].t == 'Str' and c[1].text == '.' and c[2].t == 'Space'
      and c[3].t == 'Str' and c[3].text == '.' and c[4].t == 'Space'
      and c[5].t == 'Str' and c[5].text == '.' then
    return {}
  end
end

local function notes(div)
  if not div.classes:includes('notes') then return nil end
  if NOTES == 'omitted' then return {} end
  local blocks = pandoc.Blocks({
    pandoc.RawBlock('html', '<details class="notes"'
      .. (NOTES == 'visible' and ' open' or '') .. '>\n<summary>'
      .. escape(LABEL) .. '</summary>'),
  })
  blocks:extend(div.content)
  blocks:insert(pandoc.RawBlock('html', '</details>'))
  return blocks
end

local function clamp(level)
  return math.max(1, math.min(6, level))
end

-- The shallowest heading made base, the rest kept in their places under
-- it: a piece the split cut, and a deck with no slides at headings
-- (a slide level of 0).
local function shifted(doc, base)
  local shallowest
  doc.blocks:walk({
    Header = function(header)
      if not shallowest or header.level < shallowest then
        shallowest = header.level
      end
    end,
  })
  local shift = shallowest and base - shallowest or 0
  return function(header)
    if shift == 0 then return nil end
    header.level = clamp(header.level + shift)
    return header
  end
end

-- Each heading at its level among the sections around it, in reading
-- order: a section's below the sections it's in, a slide's one below its
-- section's, and one in a slide below the slide's and the slide's own
-- headings it's under, as beamer makes any of them a block of the slide.
-- Returns the function for the deck's own headings, and one that makes
-- the function for the headings in something in a slide whatever their
-- level: its notes, a quotation, a list, a table, or a figure, where
-- they're no section, and nothing the deck's next heading is under.
local function placed(level, base)
  local open, inner, slide = {}, {}, nil
  local function under(stack, header)
    local own = header.level
    while #stack > 0 and stack[#stack] >= own do table.remove(stack) end
    header.level = clamp((slide or base + #open - 1) + 1 + #stack)
    table.insert(stack, own)
    return header
  end
  local function within()
    local stack = {}
    for i, own in ipairs(inner) do stack[i] = own end
    return function(header) return under(stack, header) end
  end
  local function heading(header)
    local own = header.level
    if own < level then
      while #open > 0 and open[#open] >= own do table.remove(open) end
      header.level = clamp(base + #open)
      table.insert(open, own)
      slide, inner = nil, {}
    elseif own == level then
      header.level = clamp(base + #open)
      slide, inner = header.level, {}
    else
      return under(inner, header)
    end
    return header
  end
  return heading, within
end

-- Where a heading is the slide's, not the deck's: its notes, and what
-- Pandoc's slide writers don't look into for slides.
local NESTED = { BlockQuote = true, BulletList = true, OrderedList = true,
                 DefinitionList = true, Table = true, Figure = true }

function Pandoc(doc)
  local recorded = doc.meta['deck-slide-level']
  if recorded == nil then return nil end
  local level = tonumber(pandoc.utils.stringify(recorded)) or 0
  local titled = doc.meta.title ~= nil
    and pandoc.utils.stringify(doc.meta.title):match('%S') ~= nil
  local base = titled and 2 or 1
  local heading, within
  if doc.meta['page-part'] ~= nil then
    heading = shifted(doc, 2)
  elseif level <= 0 then
    heading = shifted(doc, base)
  else
    heading, within = placed(level, base)
  end
  local filter = { traverse = 'topdown', Header = heading }
  if within then
    local function nested(element)
      return element:walk({ traverse = 'topdown', Header = within() }), false
    end
    for kind in pairs(NESTED) do filter[kind] = nested end
    filter.Div = function(div)
      if div.classes:includes('notes') then return nested(div) end
    end
  end
  -- In reading order.
  doc = doc:walk(filter)
  return doc:walk({ Div = notes, Para = pause })
end
