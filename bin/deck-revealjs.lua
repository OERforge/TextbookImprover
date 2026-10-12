-- deck-revealjs.lua -- what Pandoc's reveal.js writer needs to be given of
-- a deck, when lib/revealtarget.py writes its presentation, before
-- target-blocks.lua.
--
-- Speaker notes, Pandoc's ::: notes divs, which the writer writes as
-- reveal.js's notes (<aside class="notes">, shown in its speaker view, or
-- under each slide with slides.notes visible), are left out when
-- DECK_NOTES, slides.notes, is omitted.
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

return {
  {
    Div = function(div)
      if NOTES == 'omitted' and div.classes:includes('notes') then return {} end
    end,
  },
}
