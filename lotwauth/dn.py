"""Parsing of X.509 subject distinguished names as passed on by web servers."""
import re

CALLSIGN_OID = '1.3.6.1.4.1.12348.1.1'

# ASCII letters and digits only, in either case; matched before uppercasing.
CALLSIGN_RE = re.compile(r'^[A-Za-z0-9]+(/[A-Za-z0-9]+)*\Z')

# ASN.1 string types and the encodings of their contents
_DER_STRING_ENCODINGS = {
    0x0c: 'utf-8',       # UTF8String
    0x13: 'ascii',       # PrintableString
    0x14: 'latin-1',     # TeletexString
    0x16: 'ascii',       # IA5String
    0x1e: 'utf-16-be',   # BMPString
}


class InvalidDN(ValueError):
    pass


def _decode_der_string(hexstring):
    """Decode a '#'-prefixed hex DER encoding of an ASN.1 string value."""
    try:
        der = bytes.fromhex(hexstring)
        tag, length = der[0], der[1]
        offset = 2
        if length & 0x80:
            n = length & 0x7f
            length = int.from_bytes(der[2:2 + n], 'big')
            offset = 2 + n
        content = der[offset:offset + length]
        if len(content) != length:
            raise InvalidDN("truncated DER value")
        return content.decode(_DER_STRING_ENCODINGS[tag])
    except (ValueError, IndexError, KeyError) as e:
        raise InvalidDN("cannot decode DER value %r" % hexstring) from e


def _split_rfc4514(dn):
    """Split 'a=b,c=d' into (key, raw value) pairs, honouring escapes."""
    parts = []
    current = []
    i = 0
    while i < len(dn):
        c = dn[i]
        if c == '\\' and i + 1 < len(dn):
            current.append(dn[i:i + 2])
            i += 2
            continue
        if c in ',+':
            parts.append(''.join(current))
            current = []
        else:
            current.append(c)
        i += 1
    parts.append(''.join(current))
    return parts


def _unescape_rfc4514(value):
    """Undo RFC 4514 escaping: '\\,' style and '\\C3\\A4' style hex pairs."""
    out = bytearray()
    i = 0
    while i < len(value):
        c = value[i]
        if c == '\\' and i + 1 < len(value):
            pair = value[i + 1:i + 3]
            if re.fullmatch(r'[0-9a-fA-F]{2}', pair):
                out.append(int(pair, 16))
                i += 3
            else:
                out.extend(value[i + 1].encode('utf-8'))
                i += 2
        else:
            out.extend(c.encode('utf-8'))
            i += 1
    return out.decode('utf-8', errors='replace')


def parse_dn(dn):
    """
    Parse a subject DN into a dict with lowercased attribute names.

    Only the RFC 2253/4514 form produced by current web servers (nginx
    $ssl_client_s_dn, Apache 2.4) is accepted:

        emailAddress=x@example.com,CN=First Last,1.3.6.1.4.1.12348.1.1=#13054E30434C4C

    The legacy OpenSSL "oneline" form (/CN=First Last/emailAddress=...) is
    refused on purpose: it does not escape its separator, so a certificate
    holder's name could smuggle in another callsign attribute.
    """
    dn = (dn or '').strip()
    if not dn:
        raise InvalidDN("empty DN")
    if dn.startswith('/'):
        raise InvalidDN("legacy DN format is not supported")

    result = {}
    for part in _split_rfc4514(dn):
        key, sep, value = part.partition('=')
        if not sep:
            raise InvalidDN("malformed DN component")
        key = key.strip().lower()
        value = value.strip()
        if value.startswith('#'):
            value = _decode_der_string(value[1:])
        else:
            value = _unescape_rfc4514(value)
        if key == CALLSIGN_OID and key in result:
            raise InvalidDN("several callsigns in DN")
        result.setdefault(key, value)
    return result


def callsign_from_dn(dn):
    """Return the callsign, uppercased, of the holder of a LoTW certificate."""
    attrs = parse_dn(dn)

    # Validate the value as it is in the certificate: str.upper() turns some
    # non-ASCII letters into ASCII ones (ſ -> S, ß -> SS), which must not
    # become a way to spell somebody else's callsign.
    callsign = attrs.get(CALLSIGN_OID, '')
    if not CALLSIGN_RE.match(callsign):
        raise InvalidDN("no valid callsign in DN")
    return callsign.upper()
