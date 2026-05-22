"""Minimal protobuf wire-format parser for COROS training API responses."""
import struct


def read_varint(data, offset):
    """Read a protobuf varint, return (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


def read_length_delimited(data, offset):
    """Read a length-delimited field, return (raw_bytes, new_offset)."""
    length, offset = read_varint(data, offset)
    return data[offset:offset + length], offset + length


def read_fixed64(data, offset):
    """Read a fixed64, return (value, new_offset)."""
    val = struct.unpack_from("<Q", data, offset)[0] if offset + 8 <= len(data) else 0
    return val, offset + 8


def read_fixed32(data, offset):
    """Read a fixed32, return (value, new_offset)."""
    val = struct.unpack_from("<I", data, offset)[0] if offset + 4 <= len(data) else 0
    return val, offset + 4


def parse_protobuf(data, offset=0, max_depth=10):
    """Parse protobuf bytes into a Python dict. Returns (result, new_offset)."""
    if max_depth <= 0:
        return {}, offset

    result = {}
    repeated = {}  # field_num -> list

    while offset < len(data):
        try:
            tag, offset = read_varint(data, offset)
            field_num = tag >> 3
            wire_type = tag & 0x7

            if wire_type == 0:  # Varint
                val, offset = read_varint(data, offset)
                if field_num in repeated:
                    repeated[field_num].append(val)
                elif field_num in result:
                    repeated[field_num] = [result.pop(field_num), val]
                else:
                    result[field_num] = val

            elif wire_type == 1:  # Fixed64
                val, offset = read_fixed64(data, offset)
                result[field_num] = val

            elif wire_type == 2:  # Length-delimited
                raw, offset = read_length_delimited(data, offset)
                # Try to parse as string (UTF-8)
                try:
                    text = raw.decode("utf-8")
                    if all(c.isprintable() or c in "\n\r\t" for c in text) and len(text) >= 2:
                        # Might be a string; try nested proto first
                        nested, _ = parse_protobuf(raw, 0, max_depth - 1)
                        if nested:
                            # Contains valid nested message(s)
                            if field_num in repeated:
                                repeated[field_num].append(nested)
                            elif field_num in result:
                                repeated[field_num] = [result.pop(field_num), nested]
                            else:
                                result[field_num] = nested
                        else:
                            if field_num in repeated:
                                repeated[field_num].append(text)
                            elif field_num in result:
                                repeated[field_num] = [result.pop(field_num), text]
                            else:
                                result[field_num] = text
                    else:
                        # Binary - try nested proto
                        nested, _ = parse_protobuf(raw, 0, max_depth - 1)
                        if nested:
                            if field_num in repeated:
                                repeated[field_num].append(nested)
                            elif field_num in result:
                                repeated[field_num] = [result.pop(field_num), nested]
                            else:
                                result[field_num] = nested
                        else:
                            if field_num in repeated:
                                repeated[field_num].append(raw)
                            elif field_num in result:
                                repeated[field_num] = [result.pop(field_num), raw]
                            else:
                                result[field_num] = raw
                except UnicodeDecodeError:
                    # Binary blob
                    nested, _ = parse_protobuf(raw, 0, max_depth - 1)
                    if nested:
                        if field_num in repeated:
                            repeated[field_num].append(nested)
                        elif field_num in result:
                            repeated[field_num] = [result.pop(field_num), nested]
                        else:
                            result[field_num] = nested
                    else:
                        val = raw.hex()
                        if field_num in repeated:
                            repeated[field_num].append(val)
                        elif field_num in result:
                            repeated[field_num] = [result.pop(field_num), val]
                        else:
                            result[field_num] = val

            elif wire_type == 5:  # Fixed32
                val, offset = read_fixed32(data, offset)
                result[field_num] = val

            else:
                break

        except Exception:
            break

    # Merge repeated fields
    result.update(repeated)
    return result, offset


def decode_training_response(data: bytes) -> list[dict]:
    """Decode a /coros/training/program/query or /plan/query protobuf response."""
    parsed, _ = parse_protobuf(data)

    # Extract the inner message (the Any wrapper)
    # Structure: {1: status_code, 2: page_info, 3: type_url, 4: value}
    # The value (field 4) contains the actual Programs message
    # But COROS might use field 2 for the payload

    # Find the field containing the programs list
    # Usually field 2 or 3 has the paginated result
    for key, val in parsed.items():
        if isinstance(val, dict):
            # Look for repeated messages inside
            for ik, iv in val.items():
                if isinstance(iv, list) and len(iv) > 0:
                    if isinstance(iv[0], dict):
                        return iv
                elif isinstance(iv, dict):
                    # Check deeper
                    for jk, jv in iv.items():
                        if isinstance(jv, list) and len(jv) > 0:
                            if isinstance(jv[0], dict):
                                return jv

    return parsed


# For debugging: print parsed structure
def print_structure(parsed, indent=0, max_items=5):
    """Print the parsed protobuf structure for inspection."""
    prefix = "  " * indent
    if isinstance(parsed, dict):
        for k, v in list(parsed.items())[:max_items]:
            print(f"{prefix}field_{k}: ", end="")
            if isinstance(v, (dict, list)):
                print(type(v).__name__)
                print_structure(v, indent + 1, max_items)
            elif isinstance(v, str) and len(v) > 60:
                print(f'"{v[:60]}..."')
            else:
                print(repr(v))
        if len(parsed) > max_items:
            print(f"{prefix}... and {len(parsed) - max_items} more fields")
    elif isinstance(parsed, list):
        print(f"{prefix}[{len(parsed)} items]")
        for i, item in enumerate(parsed[:max_items]):
            print(f"{prefix}[{i}]:")
            print_structure(item, indent + 1, max_items)
        if len(parsed) > max_items:
            print(f"{prefix}... and {len(parsed) - max_items} more items")
    else:
        print(f"{prefix}{repr(parsed)}")
