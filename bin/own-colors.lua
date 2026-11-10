--[[
own-colors.lua -- a source's own colors in a page's and an EPUB's dark mode.

Loaded by target-blocks.lua, which runs dark_partners for a page or an EPUB.

Pandoc's stylesheets, a page's and an EPUB's, follow the reader's dark mode
(3.12 and later): they turn the text's color and the page's together,
#1a1a1a on #fdfdfd to #fdfdfd on #1a1a1a, or #cfcfc2 on #232629 in an EPUB,
with light-dark(). A color a source gives an element of its own in its
style, which the HTML, Markdown, and LaTeX readers keep (PANDOC-NOTES, The
HTML writer), doesn't turn, so dark mode leaves it beside a color that has:
a text color of its own on the dark page, a background of its own under the
dark page's light text, each read well in light mode and at 1.05:1 to
2.02:1 in dark (CNX-NOTES, item 223). So, as each element's style says:

- A text color of its own and no background: a partner for dark mode, the
  color with its lightness raised in OKLCH, its hue kept and its chroma as
  far as sRGB allows, to 4.6:1 on #232629, the lighter of the two dark
  backgrounds, as highlighting.py's colors for code are: written after the
  element's own declaration, `color: light-dark(own, partner)`, which a
  browser without light-dark() drops, keeping the first. A color that
  reads at 4.6:1 there already keeps itself, and one no lighter than the
  page's own text (#1a1a1a), black say, which says no more than the text's
  color, turns as the page's text does, to #fdfdfd, where the least that
  reads would be a gray dimmer than the text around it.
- A background of its own and no text color: the class own-background,
  for page.css to keep its text in the light mode's color in dark mode, as
  the source made it to be read on that background; and what's inside it
  is left as the source colored it, for the same background.
- Both, or a background that isn't one color (a picture, a gradient, one
  partly transparent): left as it is, and what's inside it too, since what
  it sits on can't be told.

A value that isn't a color, or not one known here (`inherit`,
`currentColor`, `transparent`, a color partly transparent, a name CSS
doesn't have), counts as none for a background and is left as it is for a
text color. Colors are read as CSS Color 4 gives them: #rgb, #rgba,
#rrggbb, and #rrggbbaa; rgb() and rgba(), with commas or spaces, numbers
or percentages; hsl() and hsla(); and CSS's 148 named colors.

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

local M = {}

-- The darker mode's lighter background, an EPUB's, and the ratio a partner
-- is raised to, as highlighting.py's are; the light mode's text, and the
-- dark mode's, a page's.
M.DARK = { 0x23, 0x26, 0x29 }
M.RATIO = 4.6
M.TEXT = { 0x1a, 0x1a, 0x1a }
M.DARK_TEXT = { 0xfd, 0xfd, 0xfd }
M.CLASS = 'own-background'

-- CSS Color 4's named colors (https://www.w3.org/TR/css-color-4/#named-colors).
local NAMED = {
  aliceblue = 'f0f8ff', antiquewhite = 'faebd7', aqua = '00ffff', aquamarine = '7fffd4',
  azure = 'f0ffff', beige = 'f5f5dc', bisque = 'ffe4c4', black = '000000',
  blanchedalmond = 'ffebcd', blue = '0000ff', blueviolet = '8a2be2', brown = 'a52a2a',
  burlywood = 'deb887', cadetblue = '5f9ea0', chartreuse = '7fff00', chocolate = 'd2691e',
  coral = 'ff7f50', cornflowerblue = '6495ed', cornsilk = 'fff8dc', crimson = 'dc143c',
  cyan = '00ffff', darkblue = '00008b', darkcyan = '008b8b', darkgoldenrod = 'b8860b',
  darkgray = 'a9a9a9', darkgreen = '006400', darkgrey = 'a9a9a9', darkkhaki = 'bdb76b',
  darkmagenta = '8b008b', darkolivegreen = '556b2f', darkorange = 'ff8c00',
  darkorchid = '9932cc', darkred = '8b0000', darksalmon = 'e9967a', darkseagreen = '8fbc8f',
  darkslateblue = '483d8b', darkslategray = '2f4f4f', darkslategrey = '2f4f4f',
  darkturquoise = '00ced1', darkviolet = '9400d3', deeppink = 'ff1493',
  deepskyblue = '00bfff', dimgray = '696969', dimgrey = '696969', dodgerblue = '1e90ff',
  firebrick = 'b22222', floralwhite = 'fffaf0', forestgreen = '228b22', fuchsia = 'ff00ff',
  gainsboro = 'dcdcdc', ghostwhite = 'f8f8ff', gold = 'ffd700', goldenrod = 'daa520',
  gray = '808080', green = '008000', greenyellow = 'adff2f', grey = '808080',
  honeydew = 'f0fff0', hotpink = 'ff69b4', indianred = 'cd5c5c', indigo = '4b0082',
  ivory = 'fffff0', khaki = 'f0e68c', lavender = 'e6e6fa', lavenderblush = 'fff0f5',
  lawngreen = '7cfc00', lemonchiffon = 'fffacd', lightblue = 'add8e6', lightcoral = 'f08080',
  lightcyan = 'e0ffff', lightgoldenrodyellow = 'fafad2', lightgray = 'd3d3d3',
  lightgreen = '90ee90', lightgrey = 'd3d3d3', lightpink = 'ffb6c1', lightsalmon = 'ffa07a',
  lightseagreen = '20b2aa', lightskyblue = '87cefa', lightslategray = '778899',
  lightslategrey = '778899', lightsteelblue = 'b0c4de', lightyellow = 'ffffe0',
  lime = '00ff00', limegreen = '32cd32', linen = 'faf0e6', magenta = 'ff00ff',
  maroon = '800000', mediumaquamarine = '66cdaa', mediumblue = '0000cd',
  mediumorchid = 'ba55d3', mediumpurple = '9370db', mediumseagreen = '3cb371',
  mediumslateblue = '7b68ee', mediumspringgreen = '00fa9a', mediumturquoise = '48d1cc',
  mediumvioletred = 'c71585', midnightblue = '191970', mintcream = 'f5fffa',
  mistyrose = 'ffe4e1', moccasin = 'ffe4b5', navajowhite = 'ffdead', navy = '000080',
  oldlace = 'fdf5e6', olive = '808000', olivedrab = '6b8e23', orange = 'ffa500',
  orangered = 'ff4500', orchid = 'da70d6', palegoldenrod = 'eee8aa', palegreen = '98fb98',
  paleturquoise = 'afeeee', palevioletred = 'db7093', papayawhip = 'ffefd5',
  peachpuff = 'ffdab9', peru = 'cd853f', pink = 'ffc0cb', plum = 'dda0dd',
  powderblue = 'b0e0e6', purple = '800080', rebeccapurple = '663399', red = 'ff0000',
  rosybrown = 'bc8f8f', royalblue = '4169e1', saddlebrown = '8b4513', salmon = 'fa8072',
  sandybrown = 'f4a460', seagreen = '2e8b57', seashell = 'fff5ee', sienna = 'a0522d',
  silver = 'c0c0c0', skyblue = '87ceeb', slateblue = '6a5acd', slategray = '708090',
  slategrey = '708090', snow = 'fffafa', springgreen = '00ff7f', steelblue = '4682b4',
  tan = 'd2b48c', teal = '008080', thistle = 'd8bfd8', tomato = 'ff6347',
  turquoise = '40e0d0', violet = 'ee82ee', wheat = 'f5deb3', white = 'ffffff',
  whitesmoke = 'f5f5f5', yellow = 'ffff00', yellowgreen = '9acd32',
}
M.NAMED = NAMED

-- Values that say no color of the element's own.
local NONE = { inherit = true, initial = true, unset = true, revert = true,
               ['revert-layer'] = true, currentcolor = true, transparent = true,
               none = true }

local function clamp(x, low, high)
  if x < low then return low elseif x > high then return high else return x end
end

-- One channel of rgb(), 0 to 255, from a number or a percentage.
local function channel(token)
  local pct = token:match('^([%d%.]+)%%$')
  if pct then return clamp(tonumber(pct) * 2.55, 0, 255) end
  local n = tonumber(token)
  return n and clamp(n, 0, 255) or nil
end

-- An alpha, 0 to 1, from a number or a percentage; nil for none given.
local function alpha(token)
  if token == nil then return 1 end
  local pct = token:match('^([%d%.]+)%%$')
  if pct then return tonumber(pct) / 100 end
  return tonumber(token)
end

local function hsl_to_rgb(h, s, l)
  h = (h % 360) / 360
  local function f(n)
    local k = (n + h * 12) % 12
    local a = s * math.min(l, 1 - l)
    return l - a * math.max(-1, math.min(k - 3, 9 - k, 1))
  end
  return f(0) * 255, f(8) * 255, f(4) * 255
end

-- A CSS color as { r, g, b }, 0 to 255, when it's one known here and opaque;
-- false for a value that says no color of its own; nil for anything else.
function M.parse(value)
  local v = value:lower():gsub('^%s+', ''):gsub('%s+$', '')
  if NONE[v] then return false end
  local hex = v:match('^#(%x+)$')
  if hex then
    if #hex == 3 or #hex == 4 then
      if #hex == 4 and hex:sub(4, 4) ~= 'f' then return nil end
      return { tonumber(hex:sub(1, 1):rep(2), 16), tonumber(hex:sub(2, 2):rep(2), 16),
               tonumber(hex:sub(3, 3):rep(2), 16) }
    elseif #hex == 6 or #hex == 8 then
      if #hex == 8 and hex:sub(7, 8) ~= 'ff' then return nil end
      return { tonumber(hex:sub(1, 2), 16), tonumber(hex:sub(3, 4), 16),
               tonumber(hex:sub(5, 6), 16) }
    end
    return nil
  end
  if NAMED[v] then return M.parse('#' .. NAMED[v]) end
  local fn, args = v:match('^(%a+)%((.*)%)$')
  if not fn then return nil end
  local parts = {}
  for token in args:gsub('/', ' / '):gsub(',', ' '):gmatch('%S+') do
    parts[#parts + 1] = token
  end
  local a
  if parts[4] == '/' then a = alpha(parts[5]) else a = alpha(parts[4]) end
  if a == nil or a < 1 then return nil end
  if fn == 'rgb' or fn == 'rgba' then
    local r, g, b = channel(parts[1] or ''), channel(parts[2] or ''), channel(parts[3] or '')
    if not (r and g and b) then return nil end
    return { r, g, b }
  elseif fn == 'hsl' or fn == 'hsla' then
    local h = tonumber((parts[1] or ''):match('^([%d%.%-]+)d?e?g?$') or '')
    local s = tonumber((parts[2] or ''):match('^([%d%.]+)%%$') or '')
    local l = tonumber((parts[3] or ''):match('^([%d%.]+)%%$') or '')
    if not (h and s and l) then return nil end
    local r, g, b = hsl_to_rgb(h, clamp(s / 100, 0, 1), clamp(l / 100, 0, 1))
    return { r, g, b }
  end
  return nil
end

local function linear(c)
  c = c / 255
  if c <= 0.04045 then return c / 12.92 end
  return ((c + 0.055) / 1.055) ^ 2.4
end

local function gamma(c)
  if c <= 0.0031308 then return 12.92 * c end
  return 1.055 * c ^ (1 / 2.4) - 0.055
end

-- WCAG's relative luminance and contrast ratio.
function M.luminance(rgb)
  return 0.2126 * linear(rgb[1]) + 0.7152 * linear(rgb[2]) + 0.0722 * linear(rgb[3])
end

function M.contrast(one, other)
  local a, b = M.luminance(one), M.luminance(other)
  if a < b then a, b = b, a end
  return (a + 0.05) / (b + 0.05)
end

local function cbrt(x)
  return x < 0 and -((-x) ^ (1 / 3)) or x ^ (1 / 3)
end

-- sRGB, 0 to 255, to OKLab (Björn Ottosson's), and back, unclipped.
local function oklab(rgb)
  local r, g, b = linear(rgb[1]), linear(rgb[2]), linear(rgb[3])
  local l = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  local m = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  local s = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
         1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
         0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
end

local function from_oklab(L, a, b)
  local l = (L + 0.3963377774 * a + 0.2158037573 * b) ^ 3
  local m = (L - 0.1055613458 * a - 0.0638541728 * b) ^ 3
  local s = (L - 0.0894841775 * a - 1.2914855480 * b) ^ 3
  return 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
         -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
         -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
end

local function in_gamut(r, g, b)
  local e = 1e-6
  return r >= -e and r <= 1 + e and g >= -e and g <= 1 + e and b >= -e and b <= 1 + e
end

-- The color at OKLCH lightness L, hue h, and as much of chroma c as sRGB
-- holds there, 0 to 255, rounded.
local function at(L, c, h)
  local low, high = 0, c
  local r, g, b = from_oklab(L, c * math.cos(h), c * math.sin(h))
  if not in_gamut(r, g, b) then
    for _ = 1, 40 do
      local mid = (low + high) / 2
      r, g, b = from_oklab(L, mid * math.cos(h), mid * math.sin(h))
      if in_gamut(r, g, b) then low = mid else high = mid end
    end
    r, g, b = from_oklab(L, low * math.cos(h), low * math.sin(h))
  end
  local function byte(x) return math.floor(clamp(gamma(clamp(x, 0, 1)), 0, 1) * 255 + 0.5) end
  return { byte(r), byte(g), byte(b) }
end

-- The partner for dark mode: the color itself where it reads at RATIO on
-- DARK; the dark mode's text where it's no lighter than the light mode's;
-- and else the least lightness that reads at RATIO, its hue kept.
function M.partner(rgb)
  if M.contrast(rgb, M.DARK) >= M.RATIO then return rgb end
  if M.luminance(rgb) <= M.luminance(M.TEXT) then return M.DARK_TEXT end
  local L, a, b = oklab(rgb)
  local c, h = math.sqrt(a * a + b * b), math.atan(b, a)
  local low, high = L, 1
  for _ = 1, 40 do
    local mid = (low + high) / 2
    if M.contrast(at(mid, c, h), M.DARK) >= M.RATIO then high = mid else low = mid end
  end
  return at(high, c, h)
end

function M.hex(rgb)
  return string.format('#%02x%02x%02x', math.floor(rgb[1] + 0.5), math.floor(rgb[2] + 0.5),
                       math.floor(rgb[3] + 0.5))
end

-- A style's declarations, each { property, value, important }, split at
-- semicolons outside parentheses and quotes.
function M.declarations(style)
  local out, depth, quote, start = {}, 0, nil, 1
  local function take(stop)
    local text = style:sub(start, stop)
    local prop, value = text:match('^%s*([%w%-]+)%s*:%s*(.-)%s*$')
    if prop then
      local important = false
      local bare = value:match('^(.-)%s*!%s*[Ii][Mm][Pp][Oo][Rr][Tt][Aa][Nn][Tt]$')
      if bare then value, important = bare, true end
      out[#out + 1] = { prop:lower(), value, important }
    end
  end
  for i = 1, #style do
    local ch = style:sub(i, i)
    if quote then
      if ch == quote then quote = nil end
    elseif ch == '"' or ch == "'" then quote = ch
    elseif ch == '(' then depth = depth + 1
    elseif ch == ')' then depth = math.max(0, depth - 1)
    elseif ch == ';' and depth == 0 then
      take(i - 1)
      start = i + 1
    end
  end
  take(#style)
  return out
end

-- What an element's style says: its text color's value and the parsed
-- color (false for none, nil for one not known here), and its background:
-- 'none', 'color' (one opaque color), or 'other'.
local function colors(style)
  local text, background = nil, 'none'
  for _, d in ipairs(M.declarations(style)) do
    local prop, value = d[1], d[2]
    if prop == 'color' then
      text = { value = value, rgb = M.parse(value), important = d[3] }
    elseif prop == 'background-color' then
      local rgb = M.parse(value)
      background = rgb and 'color' or (rgb == false and 'none' or 'other')
    elseif prop == 'background' then
      local rgb = M.parse(value)
      background = rgb and 'color' or (rgb == false and 'none' or 'other')
    elseif prop == 'background-image' then
      if M.parse(value) ~= false then background = 'other' end
    end
  end
  return text, background
end

-- An element's, a row's, or a cell's attributes made over as its style
-- says (the head of this file), and given back to it, since Pandoc hands a
-- filter a copy of them; true where what's inside it is to be left as it
-- is.
local function own(holder)
  local attr = holder.attr
  local style = attr.attributes.style
  if style == nil or style == '' then return false end
  local text, background = colors(style)
  if background == 'other' then return true end
  if background == 'color' then
    if not (text and text.rgb ~= false) then
      attr.classes:insert(M.CLASS)
      holder.attr = attr
    end
    return true
  end
  if text and text.rgb then
    local partner = M.partner(text.rgb)
    if M.hex(partner) ~= M.hex(text.rgb) then
      attr.attributes.style = style:gsub('%s*;?%s*$', '') .. '; color: light-dark(' ..
        text.value .. ', ' .. M.hex(partner) .. ')' .. (text.important and ' !important' or '')
      holder.attr = attr
    end
  end
  return false
end

local filter

-- A table's rows and cells, each as its style says, and what's in a cell
-- whose background isn't its own made over too; each part given back to
-- what holds it.
local function table_cells(tbl)
  local function rows(list)
    local out = pandoc.List({})
    for _, row in ipairs(list) do
      local skip = own(row)
      local cells = pandoc.List({})
      for _, cell in ipairs(row.cells) do
        if not (skip or own(cell)) then
          cell.contents = cell.contents:walk(filter)
        end
        cells:insert(cell)
      end
      row.cells = cells
      out:insert(row)
    end
    return out
  end
  if own(tbl) then return tbl, false end
  local head = tbl.head
  head.rows = rows(head.rows)
  tbl.head = head
  local bodies = pandoc.List({})
  for _, body in ipairs(tbl.bodies) do
    body.head = rows(body.head)
    body.body = rows(body.body)
    bodies:insert(body)
  end
  tbl.bodies = bodies
  local foot = tbl.foot
  foot.rows = rows(foot.rows)
  tbl.foot = foot
  local caption = tbl.caption
  caption.long = caption.long:walk(filter)
  tbl.caption = caption
  return tbl, false
end

local function element(el)
  if own(el) then return el, false end
  return el
end

filter = {
  traverse = 'topdown',
  Span = element, Div = element, Header = element, Link = element, Code = element,
  CodeBlock = element, Figure = element, Table = table_cells,
}

-- A page's or an EPUB's document, each element's own colors given what dark
-- mode needs.
function M.dark_partners(doc)
  return doc:walk(filter)
end

return M
