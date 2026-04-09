USE [PI]
GO

IF @@SERVERNAME IN ('IN-SVR-SQLTDB01\DEV01', 'IN-SVR-SQLTDB03\QA01', 'IN-SVR-SQLTDB02\QA01')
BEGIN
  DELETE [li].[NotaInformacionAsociada]

  DELETE [li].[RequerimientoInformacionAsociada]

  --TODO: INsertar con algo que pueda servir para mockear
  INSERT INTO [li].[RequerimientoInformacionAsociada] (
    [RequerimientoInformacionAsociadaEstadoId],
    [RequerimientoInformacionAsociadaCodigo],
    [CausaId],
    [RequerimientoInformacionAsociadaLegacyId],
    [EsUrgente],
    [PlazoEnHoras]
    )
  SELECT DISTINCT --ED.ID, ED.NRODOCOJ,ED.FECHADOC, CT.DESCRIPCION AS DESTINATARIO,ISNULL(CT.IDCIATEL,0) AS IDORG, LF.ESTADO,
    (ED.ExpedienteId % 5) + 1 RequerimientoInformacionAsociadaEstadoId,
    ED.NroDocOJ RequerimientoInformacionAsociadaCodigo,
    ED.ExpedienteId CausaId,
    edre.Id RequerimientoInformacionAsociadaLegacyId,
    ME.Urgente EsUrgente,
    ME.Plazo PlazoEnHoras
  FROM OJ.dbo.EXPEDIENTES_DOCS AS ED
  INNER JOIN OJ.dbo.LOGNOTASFIRMAE AS LF ON ED.ID = LF.IDNOTAS
  INNER JOIN OJ.dbo.LOGNOTAS AS LN ON LN.EDID_NOTAS = LF.IDNOTAS
  INNER JOIN OJ.dbo.EXPEDIENTES_DOCSOBS AS EDO WITH (NOLOCK) ON ED.ID = EDO.EXPEDIENTEDOCID
  INNER JOIN OJ.dbo.Expedientes_DocsRE AS edre ON ed.id = edre.expedientedocidnota
  INNER JOIN (
    SELECT TOP 500 ed.ExpedienteId,
      edre.id DocsREId,
      count(DISTINCT ct.IdCiaTel) countCiaTel
    FROM OJ.dbo.Expedientes_DocsRE AS edre
    INNER JOIN OJ.dbo.EXPEDIENTES_DOCS AS ED ON ed.id = edre.expedientedocidnota
    INNER JOIN OJ.dbo.RelReCiaTel AS rrct ON edre.id = rrct.idre
    INNER JOIN OJ.dbo.CIATEL AS CT ON rrct.IDCIATEL = CT.IDCIATEL
    WHERE 1 = 1
      AND ed.FechaAltaSistema > getdate() - 20
    GROUP BY ed.ExpedienteId,
      edre.id
    ORDER BY countCiaTel DESC
    ) a ON a.DocsREId = edre.id
    AND ed.ExpedienteId = a.ExpedienteId
  INNER JOIN OJ.dbo.ME_Rel_ED MERE ON MERE.ExpedienteDocId = EDRE.ExpedienteDocId
  INNER JOIN OJ.dbo.ME ME ON MERE.MEId = ME.Id
  --INNER JOIN oj.dbo.Expediente_Nomina_H h ON h.IdExpediente = ed.ExpedienteId
  LEFT JOIN pi.[li].[RequerimientoInformacionAsociada] ria ON ria.RequerimientoInformacionAsociadaLegacyId = edre.Id
  WHERE 1 = 1
    AND ria.RequerimientoInformacionAsociadaLegacyId IS NULL
    AND NOT (
      ED.NRODOCOJ LIKE '%-AW-%'
      OR ED.NRODOCOJ LIKE '%-RW-%'
      )
  -- AND (ED.FECHADOC >= CONVERT(CHAR(8), (GETDATE() - 20), 112))
  -- AND (ED.FECHADOC < CONVERT(CHAR(8), (GETDATE()), 112))
  	-- AND h.FechaHasta IS NULL
  	-- AND h.MaterialTipoId = 2
  ORDER BY edre.Id DESC

  IF @@ROWCOUNT <= 0
  BEGIN
      ;

    THROW 50000,
      'Error insertando registros en la tabla [li].[RequerimientoInformacionAsociada] para la funcionalidad InfoAsociadaDiDi',
      1;
  END

  -- SELECT 
  -- 	RequerimientoInformacionAsociadaCodigo,RequerimientoInformacionAsociadaLegacyId, count( distinct CausaId)
  -- FROM [li].[RequerimientoInformacionAsociada] group by RequerimientoInformacionAsociadaCodigo,RequerimientoInformacionAsociadaLegacyId
  -- having count(*)>1
  -- SELECT 
  -- 	CausaId, count( distinct RequerimientoInformacionAsociadaCodigo)
  -- FROM [li].[RequerimientoInformacionAsociada] group by CausaId
  -- having count(*)>1
  -- order by 2 desc
  INSERT INTO [li].[NotaInformacionAsociada] (
    [RequerimientoInformacionAsociadaId],
    [CiaTelId],
    [NotaInformacionAsociadaEstadoId]
    )
  SELECT DISTINCT ria.RequerimientoInformacionAsociadaId RequerimientoInformacionAsociadaId,
    ct.IdCiaTel CiaTelId,
    (ct.IdCiaTel % 5) + 1 NotaInformacionAsociadaEstadoId
  FROM pi.[li].[RequerimientoInformacionAsociada] ria
  INNER JOIN OJ.dbo.Expedientes_DocsRE AS edre ON ria.RequerimientoInformacionAsociadaLegacyId = edre.Id
  INNER JOIN OJ.dbo.EXPEDIENTES_DOCS AS ED ON ed.id = edre.expedientedocidnota
  INNER JOIN OJ.dbo.RelReCiaTel AS rrct ON edre.id = rrct.idre
  INNER JOIN OJ.dbo.CIATEL AS CT ON rrct.IDCIATEL = CT.IDCIATEL
  LEFT JOIN pi.[li].[NotaInformacionAsociada] n ON n.RequerimientoInformacionAsociadaId = ria.RequerimientoInformacionAsociadaId
  WHERE 1 = 1
    AND n.RequerimientoInformacionAsociadaId IS NULL
  ORDER BY RequerimientoInformacionAsociadaId,
    CiaTelId

  IF @@ROWCOUNT <= 0
  BEGIN
      ;

    THROW 50000,
      'Error insertando registros en la tabla [li].[RequerimientoInformacionAsociada] para la funcionalidad InfoAsociadaDiDi',
      1;
  END
END
