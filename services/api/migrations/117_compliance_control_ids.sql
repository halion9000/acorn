-- The compliance catalogs now list every control of each framework, using the current numbering: ISO/IEC 27001:2022 Annex A (it used the 2013 numbers) and NIST CSF 2.0 (it used 1.1 ids).
-- Evidence already recorded against an old id keeps pointing at the same subject under its new id. Safe to run again: once renamed, nothing matches.
UPDATE aisoc_compliance_evidence SET control_id = CASE control_id
    WHEN 'A.12.4.1' THEN 'A.8.15'
    WHEN 'A.12.4.2' THEN 'A.8.15'
    WHEN 'A.16.1.2' THEN 'A.6.8'
    WHEN 'A.9.2.1' THEN 'A.5.16'
END
WHERE framework = 'ISO27001' AND control_id IN ('A.12.4.1', 'A.12.4.2', 'A.16.1.2', 'A.9.2.1');

UPDATE aisoc_compliance_evidence SET control_id = CASE control_id
    WHEN 'DE.AE-1' THEN 'DE.AE-02'
    WHEN 'DE.CM-1' THEN 'DE.CM-01'
    WHEN 'RS.AN-1' THEN 'RS.AN-03'
    WHEN 'RS.MI-2' THEN 'RS.MI-02'
END
WHERE framework = 'NIST-CSF' AND control_id IN ('DE.AE-1', 'DE.CM-1', 'RS.AN-1', 'RS.MI-2');
