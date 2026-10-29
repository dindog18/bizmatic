"""Bound table discovery and OOXML expansion before invoking document parsers.

These checks are not a sandbox for all native parser operations.
"""
import struct
import zipfile
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, is_zipfile

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2048
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PAGE_EDGES = 512
MAX_DOCUMENT_EDGES = 4096
CHUNK_BYTES = 64 * 1024


def check_file_size(path):
    if Path(path).stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Document exceeds the 25 MiB extraction limit. Split it into smaller files.')


def _check_archive_directory(source):
    # Use the pinned Python 3.14 reader's bounded EOCD/ZIP64 resolver so the
    # preflight walks exactly the directory ZipFile will consume, including
    # prepended data. Do not construct its eager ZipInfo index yet.
    end = zipfile._EndRecData(source)
    if not end:
        raise ValueError('Office archive has no valid directory.')
    size = end[zipfile._ECD_SIZE]
    start = end[zipfile._ECD_LOCATION] - size
    if start < 0 or not 0 <= size <= MAX_FILE_BYTES:
        raise ValueError('Office archive directory size or offset is invalid.')
    source.seek(start)
    consumed, count = 0, 0
    while consumed < size:
        count += 1
        if count > MAX_ARCHIVE_MEMBERS:
            raise ValueError('Office archive has too many entries.')
        header = source.read(46)
        if len(header) != 46 or header[:4] != b'PK\x01\x02':
            raise ValueError('Office archive directory is invalid.')
        lengths = struct.unpack_from('<HHH', header, 28)
        consumed += 46 + sum(lengths)
        if consumed > size:
            raise ValueError('Office archive directory is truncated.')
        source.seek(sum(lengths), 1)


def check_office_archive(path, *, required=True):
    """Validate actual DEFLATE output, not just attacker-controlled ZIP sizes.

    A forged small file_size can still make ZipFile.read inflate a large buffer
    before truncating it. Stream raw members with an explicit output bound and
    require the actual size, CRC and stream end to match the package metadata.
    """
    check_file_size(path)
    if not required and not is_zipfile(path):
        return  # Legacy XLS is not an OOXML ZIP package.
    try:
        with open(path, 'rb') as source:
            _check_archive_directory(source)
        with open(path, 'rb') as source, ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError('Office archive has too many entries.')
            names, expanded, compressed = set(), 0, 0
            for member in members:
                if member.filename in names:
                    raise ValueError('Office archive contains duplicate entries.')
                names.add(member.filename)
                if member.flag_bits & 1 or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError('Office archive encryption or compression is unsupported.')
                expanded += member.file_size
                compressed += member.compress_size
                if member.file_size > MAX_MEMBER_BYTES or expanded > MAX_EXPANDED_BYTES:
                    raise ValueError('Office archive exceeds the expanded-size limit.')
                if compressed > MAX_FILE_BYTES:
                    raise ValueError('Office archive exceeds the compressed-size limit.')
                # Let zipfile verify local names, overlap and header consistency
                # without asking it to decompress any content.
                with archive.open(member):
                    pass
                source.seek(member.header_offset)
                header = source.read(30)
                if len(header) != 30 or header[:4] != b'PK\x03\x04':
                    raise ValueError('Office archive has an invalid entry header.')
                name_size, extra_size = struct.unpack_from('<HH', header, 26)
                source.seek(name_size + extra_size, 1)
                remaining, actual, checksum = member.compress_size, 0, 0
                decoder = zlib.decompressobj(-15) if member.compress_type == ZIP_DEFLATED else None
                while remaining:
                    chunk = source.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ValueError('Office archive is truncated.')
                    remaining -= len(chunk)
                    pending = chunk
                    while True:
                        output = decoder.decompress(pending, min(CHUNK_BYTES, member.file_size - actual + 1)) if decoder else pending
                        actual += len(output)
                        checksum = zlib.crc32(output, checksum)
                        if actual > member.file_size:
                            raise ValueError('Office archive entry size does not match its content.')
                        if decoder and decoder.unused_data:
                            raise ValueError('Office archive entry has trailing compressed data.')
                        pending = decoder.unconsumed_tail if decoder else b''
                        # zlib can buffer output even after consuming the last
                        # input byte. Drain it in bounded chunks as well.
                        if decoder is None or decoder.eof or not pending and not output:
                            break
                if actual != member.file_size or checksum != member.CRC or decoder and not decoder.eof:
                    raise ValueError('Office archive entry size or checksum is invalid.')
    except (BadZipFile, zlib.error, NotImplementedError, RuntimeError) as error:
        raise ValueError('Office archive is invalid or unsupported.') from error


def pdf_edge_cost(page):
    # Rectangles/quads expand into four edges; reserve further edges for closed
    # paths and connected graphics bounds. Count items within a single path too.
    cost = 0
    for drawing in page.get_drawings():
        cost += 4 * len(drawing.get('items', ())) + 5
        if cost > MAX_PAGE_EDGES:
            raise ValueError('PDF page exceeds the table-complexity limit. Split or simplify this PDF.')
    return cost
