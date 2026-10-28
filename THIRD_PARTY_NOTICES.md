# Third-party geometry and source references

MuseAutoLab includes original Jubilee hardware CAD by **Joshua Vasquez / Machine
Agency, University of Washington**, under the **Creative Commons Attribution 4.0
International license (CC BY 4.0)**. This geometry has its own license; do not infer
that MuseAutoLab owns it or that a software license overrides it.

- Upstream project: https://github.com/machineagency/jubilee
- Pinned revision: `c877bd2e889560c83da2a68479641a4f7f0d9b83`
- Original file: `frame/cads/STEP/jubilee.STEP`
- Source: https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP
- License notice: https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/license.txt
- License terms: https://creativecommons.org/licenses/by/4.0/
- Original STEP SHA-256: `533417712183775a544802ae29a6f94d50ef0839bc2f24f68bce7a048798afea`

The repository stores this file losslessly compressed as
`app/assets/jubilee-c877bd2.step.gz`, with adjacent attribution and provenance.
The viewer's two GLB files are simplified tessellations of its fixed parts and
original build-plate subassembly. The app reorients the assembly into its
coordinate system, proposes a vertical pose for that subassembly and adds
separate custom parts. It does not rescale source geometry. These modifications
do not establish physical travel, compatible interfaces or working hardware.
Exports include the original compressed source, notice, provenance and assembly
transformation. Preserve attribution, license link and modification notices when
redistributing the source or derived geometry. No upstream endorsement is claimed.

Science Jubilee is cited as a separately licensed integration reference; no
Science Jubilee driver or tool CAD is included. Manufacturer dimensions from
Pololu, Raspberry Pi and Opentrons are documented nominal envelopes, not
redistributed vendor CAD. Their exact scopes, dates, URLs and unresolved interfaces
are in `app/data/design-references-2026-10-28.json` and each project's source bindings.
