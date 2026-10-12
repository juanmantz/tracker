"""Insert the owner's project catalog into an Apple-built, unsigned flat PKG.

The signed application payload and its BOM remain byte-for-byte unchanged.
Only the existing bootstrap JSON in the installer Scripts archive changes.
"""
import argparse
import bz2
import copy
import gzip
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path


def read_xar(path):
    blob = Path(path).read_bytes()
    magic, header_size, version, compressed_size, raw_size, algorithm = struct.unpack('>IHHQQI', blob[:28])
    assert magic == 0x78617221 and version == 1 and algorithm == 1
    toc_bytes = blob[header_size:header_size+compressed_size]
    raw = zlib.decompress(toc_bytes)
    assert len(raw) == raw_size
    heap = blob[header_size+compressed_size:]
    tree = ET.fromstring(raw)
    checksum = tree.find('toc/checksum')
    start = int(checksum.findtext('offset'))
    assert heap[start:start+20] == hashlib.sha1(toc_bytes).digest(), 'Invalid XAR table checksum'
    files = []
    def walk(parent, prefix=''):
        for node in parent.findall('file'):
            name = prefix + node.findtext('name')
            if node.findtext('type') == 'directory':
                walk(node, name+'/')
            else:
                data = node.find('data')
                offset, length = int(data.findtext('offset')), int(data.findtext('length'))
                archived = heap[offset:offset+length]
                check = data.find('archived-checksum')
                if check is not None and check.get('style') == 'sha1':
                    assert hashlib.sha1(archived).hexdigest() == check.text
                files.append((name,node,archived))
    walk(tree.find('toc'))
    return tree, files


def unpack_data(node, body):
    encoding = node.find('data/encoding').get('style')
    if encoding == 'application/octet-stream': return body
    if encoding == 'application/x-gzip': return zlib.decompress(body)
    if encoding == 'application/x-bzip2': return bz2.decompress(body)
    raise ValueError('Unsupported XAR encoding: '+encoding)


def pack_data(node, body):
    encoding = node.find('data/encoding').get('style')
    if encoding == 'application/octet-stream': return body
    if encoding == 'application/x-gzip': return zlib.compress(body)
    if encoding == 'application/x-bzip2': return bz2.compress(body)
    raise ValueError('Unsupported XAR encoding: '+encoding)


def replace_cpio(raw, catalog):
    result = bytearray()
    offset, replaced = 0, 0
    while offset < len(raw) and raw[offset:offset+6] in (b'070707', b'070701'):
        start = offset
        magic = raw[offset:offset+6]
        if magic == b'070707':
            header = bytearray(raw[offset:offset+76])
            name_size, size = int(header[59:65],8), int(header[65:76],8)
            offset += 76
            name = raw[offset:offset+name_size]
            offset += name_size
            body = raw[offset:offset+size]
            offset += size
        else:
            header = bytearray(raw[offset:offset+110])
            size, name_size = int(header[54:62],16), int(header[94:102],16)
            offset += 110
            name = raw[offset:offset+name_size]
            offset = (offset+name_size+3)&~3
            body = raw[offset:offset+size]
            offset = (offset+size+3)&~3
        if name.rstrip(b'\0').split(b'/')[-1] == b'bootstrap-projects.json':
            body = catalog
            replaced += 1
        if magic == b'070707':
            header[65:76] = f'{len(body):011o}'.encode()
            result.extend(header+name+body)
        else:
            header[54:62] = f'{len(body):08x}'.encode()
            result.extend(header+name)
            result.extend(b'\0'*((-len(result))%4))
            result.extend(body)
            result.extend(b'\0'*((-len(result))%4))
        if name.rstrip(b'\0') == b'TRAILER!!!': break
        assert offset > start
    assert replaced == 1, 'Installer must contain exactly one existing bootstrap catalog'
    result.extend(b'\0'*((-len(result))%512))
    return bytes(result)


def personalize(source, destination, catalog):
    tree, files = read_xar(source)
    bodies = []
    scripts_found = 0
    for name, node, archived in files:
        if name == 'DreamsTime.pkg/Scripts':
            body = unpack_data(node, archived)
            assert body[:2] == b'\x1f\x8b'
            body = gzip.compress(replace_cpio(gzip.decompress(body), catalog), mtime=0)
            archived = pack_data(node, body)
            data = node.find('data')
            data.find('size').text = str(len(body))
            for tag, content in (('archived-checksum',archived),('extracted-checksum',body)):
                check = data.find(tag)
                if check is not None:
                    assert check.get('style') == 'sha1'
                    check.text = hashlib.sha1(content).hexdigest()
            scripts_found += 1
        bodies.append((node,archived))
    assert scripts_found == 1
    checksum = tree.find('toc/checksum')
    checksum.set('style','sha1')
    checksum.find('offset').text = '0'
    checksum.find('size').text = '20'
    offset = 20
    for node, body in bodies:
        data = node.find('data')
        data.find('offset').text = str(offset)
        data.find('length').text = str(len(body))
        offset += len(body)
    raw = ET.tostring(tree,encoding='utf-8',xml_declaration=True)
    toc = zlib.compress(raw)
    header = struct.pack('>IHHQQI',0x78617221,28,1,len(toc),len(raw),1)
    Path(destination).write_bytes(header+toc+hashlib.sha1(toc).digest()+b''.join(b for _,b in bodies))
    # Re-read all checksums and establish that the executable payload was preserved.
    _, verified = read_xar(destination)
    original = {name:body for name,_,body in files}
    for name,_,body in verified:
        if name != 'DreamsTime.pkg/Scripts': assert body == original[name], 'Unexpected payload change'


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('catalog',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    catalog=json.loads(args.catalog.read_text())
    assert isinstance(catalog.get('nodes'),list) and isinstance(catalog.get('revision'),int)
    assert all(set(n).issubset({'id','name','kind','fields'}) and set(n.get('fields',{})).issubset({'links'}) for n in catalog['nodes'])
    personalize(args.source,args.destination,json.dumps(catalog,ensure_ascii=False).encode())
    print(json.dumps({'file':str(args.destination),'bytes':args.destination.stat().st_size,'projects':len(catalog['nodes'])}))
