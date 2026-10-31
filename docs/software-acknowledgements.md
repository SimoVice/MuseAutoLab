# Development guidance and software attribution

MuseAutoLab's CAD export review used the `lab-hardware-cad` guidance from K-Dense Scientific Agent Skills, alongside the installed build123d version. That guidance informed geometry provenance, explicit unchecked interfaces and numeric/visual review. It is development tooling, not a product runtime dependency or evidence of hardware validation.

Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*. [arXiv:2609.00065](https://doi.org/10.48550/arXiv.2609.00065). Bibliographic record rechecked on 2026-10-30; the consulted record was revised on 2026-09-02. The labware-adapter and fabrication guidance also informed the parametric tube rack's declared fit assumptions and actual-solid/visual checks. It does not supply measured tube dimensions or certify a printed part.

The bibliographic record was rechecked on 2026-10-31. The same labware-adapter,
fabrication and validation guidance informed the rim-supported tip holder,
fit coupon and actual-solid checks. All example dimensions are synthetic; the
guidance supplies no measured tip fit or printer accuracy.

Pinned product dependencies and optional development-skill sources are listed in the README. Skill files remain outside the public product checkout. Generated concept geometry does not establish mechanical fit, manufacturability or laboratory performance.

The same labware-adapter guidance informed the shallow 96-well plate holder's
base-footprint tolerance budget and reopened-solid/visual checks. Its reference
well geometry comes separately from the pinned Opentrons software definition;
see [third-party notices](../THIRD_PARTY_NOTICES.md). No skill supplies physical
plate measurements or validates printing and laboratory use.


The bundled labware example photograph is by **Gannu03**, [Laboratory microcentrifuge tubes and pipette tips 01](https://commons.wikimedia.org/wiki/File:Laboratory_microcentrifuge_tubes_and_pipette_tips_01.jpg), **CC BY-SA 4.0**. [Asset attribution and changes](../web/public/examples/README.md) apply to that photograph; it is not original MuseAutoLab work. The surrounding project is not assigned a new license by inclusion of this asset.
