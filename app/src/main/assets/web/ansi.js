/**
 * Minimal ANSI SGR -> HTML converter.
 *
 * Libraries like rich and click emit colour escapes as soon as the stream
 * claims to be a TTY (which PyCmd's stdout does). Rendering them properly is
 * the difference between a real terminal and a wall of "[36m" noise.
 *
 * Only SGR (`ESC [ ... m`) is interpreted; every other escape sequence is
 * swallowed so cursor moves and title sets never leak into the output.
 */
(function (global) {
  'use strict';

  // Group 1 captures SGR parameters; the other alternatives match - and so
  // discard - OSC strings, remaining CSI sequences, and lone two-byte escapes.
  var ESCAPE_PATTERN =
    /\x1b\[([0-9;:]*)m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b[@-Z\\-_]/g;

  var HTML_ESCAPES = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  };

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, function (char) {
      return HTML_ESCAPES[char];
    });
  }

  /** Maps a 256-colour index onto the 16 palette slots the stylesheet defines. */
  function palette256(index) {
    if (index < 16) {
      return index;
    }
    if (index >= 232) {
      // Greyscale ramp: dark half reads as "dim", light half as "bright white".
      return index < 244 ? 8 : 15;
    }
    // 6x6x6 cube: pick the dominant channel.
    var value = index - 16;
    var r = Math.floor(value / 36);
    var g = Math.floor((value % 36) / 6);
    var b = value % 6;
    var max = Math.max(r, g, b);
    if (max === 0) {
      return 0;
    }
    var bright = max >= 4 ? 8 : 0;
    if (r === max && g === max) return bright + 3;
    if (r === max && b === max) return bright + 5;
    if (g === max && b === max) return bright + 6;
    if (r === max) return bright + 1;
    if (g === max) return bright + 2;
    return bright + 4;
  }

  function newState() {
    return { fg: null, bg: null, bold: false, italic: false, underline: false, dim: false };
  }

  function applyCodes(state, codes) {
    for (var i = 0; i < codes.length; i += 1) {
      var code = codes[i];
      if (isNaN(code)) {
        continue;
      }
      if (code === 0) {
        state.fg = null;
        state.bg = null;
        state.bold = false;
        state.italic = false;
        state.underline = false;
        state.dim = false;
      } else if (code === 1) {
        state.bold = true;
      } else if (code === 2) {
        state.dim = true;
      } else if (code === 3) {
        state.italic = true;
      } else if (code === 4) {
        state.underline = true;
      } else if (code === 22) {
        state.bold = false;
        state.dim = false;
      } else if (code === 23) {
        state.italic = false;
      } else if (code === 24) {
        state.underline = false;
      } else if (code >= 30 && code <= 37) {
        state.fg = code - 30;
      } else if (code === 39) {
        state.fg = null;
      } else if (code >= 40 && code <= 47) {
        state.bg = code - 40;
      } else if (code === 49) {
        state.bg = null;
      } else if (code >= 90 && code <= 97) {
        state.fg = code - 90 + 8;
      } else if (code >= 100 && code <= 107) {
        state.bg = code - 100;
      } else if (code === 38 || code === 48) {
        var target = code === 38 ? 'fg' : 'bg';
        var mode = codes[i + 1];
        if (mode === 5) {
          state[target] = palette256(codes[i + 2] || 0);
          i += 2;
        } else if (mode === 2) {
          // Truecolour: collapse to the nearest palette slot.
          var r = codes[i + 2] || 0;
          var g = codes[i + 3] || 0;
          var b = codes[i + 4] || 0;
          state[target] = nearestPalette(r, g, b);
          i += 4;
        }
      }
    }
  }

  function nearestPalette(r, g, b) {
    var max = Math.max(r, g, b);
    if (max < 40) return 0;
    var bright = max >= 170 ? 8 : 0;
    var threshold = max * 0.6;
    var hot = [r >= threshold, g >= threshold, b >= threshold];
    if (hot[0] && hot[1] && hot[2]) return bright + 7;
    if (hot[0] && hot[1]) return bright + 3;
    if (hot[0] && hot[2]) return bright + 5;
    if (hot[1] && hot[2]) return bright + 6;
    if (hot[0]) return bright + 1;
    if (hot[1]) return bright + 2;
    return bright + 4;
  }

  function classesFor(state) {
    var classes = [];
    if (state.bold) classes.push('b');
    if (state.italic) classes.push('i');
    if (state.underline) classes.push('u');
    if (state.dim) classes.push('d');
    if (state.fg !== null) classes.push('fg' + state.fg);
    if (state.bg !== null && state.bg < 8) classes.push('bg' + state.bg);
    return classes;
  }

  /**
   * Converts a chunk of text to HTML, carrying colour state across calls so a
   * sequence split between two writes still renders correctly.
   */
  function toHtml(text, state) {
    var out = '';
    var lastIndex = 0;
    var match;

    ESCAPE_PATTERN.lastIndex = 0;
    while ((match = ESCAPE_PATTERN.exec(text)) !== null) {
      out += wrap(text.slice(lastIndex, match.index), state);
      if (match[1] !== undefined) {
        var raw = match[1].length ? match[1] : '0';
        applyCodes(state, raw.split(';').map(function (part) {
          return parseInt(part, 10);
        }));
      }
      lastIndex = match.index + match[0].length;
    }
    out += wrap(text.slice(lastIndex), state);
    return out;
  }

  function wrap(segment, state) {
    if (!segment) {
      return '';
    }
    // Carriage returns without a newline would otherwise stack invisible text.
    segment = segment.replace(/\r(?!\n)/g, '');
    var escaped = escapeHtml(segment);
    var classes = classesFor(state);
    if (!classes.length) {
      return escaped;
    }
    return '<span class="' + classes.join(' ') + '">' + escaped + '</span>';
  }

  global.Ansi = {
    newState: newState,
    toHtml: toHtml,
    escapeHtml: escapeHtml
  };
})(window);
