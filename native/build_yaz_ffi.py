"""Build the out-of-line CFFI module linked to the pinned YAZ runtime."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cffi import FFI

ffibuilder = FFI()
ffibuilder.cdef(
    """
    typedef struct ZOOM_options_p *ZOOM_options;
    typedef struct ZOOM_connection_p *ZOOM_connection;
    typedef struct ZOOM_query_p *ZOOM_query;
    typedef struct ZOOM_resultset_p *ZOOM_resultset;
    typedef struct ZOOM_record_p *ZOOM_record;

    ZOOM_options ZOOM_options_create(void);
    void ZOOM_options_destroy(ZOOM_options opt);
    void ZOOM_options_set(ZOOM_options opt, const char *name, const char *value);

    ZOOM_connection ZOOM_connection_create(ZOOM_options options);
    void ZOOM_connection_connect(ZOOM_connection c, const char *host, int portnum);
    void ZOOM_connection_destroy(ZOOM_connection c);
    int ZOOM_connection_error(ZOOM_connection c, const char **cp, const char **addinfo);
    int ZOOM_connection_last_event(ZOOM_connection c);

    ZOOM_query ZOOM_query_create(void);
    void ZOOM_query_destroy(ZOOM_query q);
    int ZOOM_query_prefix(ZOOM_query q, const char *str);

    ZOOM_resultset ZOOM_connection_search(ZOOM_connection c, ZOOM_query q);
    void ZOOM_resultset_destroy(ZOOM_resultset r);
    size_t ZOOM_resultset_size(ZOOM_resultset r);
    void ZOOM_resultset_records(
        ZOOM_resultset r, ZOOM_record *recs, size_t start, size_t count
    );
    ZOOM_record ZOOM_resultset_record_immediate(ZOOM_resultset r, size_t pos);
    const char *ZOOM_record_get(ZOOM_record rec, const char *type, int *len);
    int ZOOM_record_error(
        ZOOM_record rec, const char **msg, const char **addinfo, const char **diagset
    );

    int ZOOM_event(int no, ZOOM_connection *connections);
    unsigned long yaz_version(char *version_str, char *sha1_str);
    """
)

yaz_home = Path(os.environ.get("YAZ_HOME", "native/yaz"))
include_dirs = [str(yaz_home / "include")]
library_dirs = [str(yaz_home / "lib")]

ffibuilder.set_source(
    "z3950_search_for_marc._yaz_native",
    "#include <yaz/zoom.h>\n#include <yaz/yaz-version.h>",
    include_dirs=include_dirs,
    library_dirs=library_dirs,
    libraries=["yaz5" if os.name == "nt" else "yaz"],
)

if __name__ == "__main__":
    output = Path(ffibuilder.compile(tmpdir="build/cffi", verbose=True))
    destination = Path("src/z3950_search_for_marc") / output.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, destination)
    print(destination)
