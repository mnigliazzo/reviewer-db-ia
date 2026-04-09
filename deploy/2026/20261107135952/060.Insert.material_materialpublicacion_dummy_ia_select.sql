USE [PI]
GO

IF @@SERVERNAME IN ('IN-SVR-SQLTDB01\DEV01', 'IN-SVR-SQLTDB03\QA01', 'IN-SVR-SQLTDB02\QA01')
BEGIN
  DECLARE @MaterialId TABLE (MaterialId BIGINT)

  INSERT @MaterialId
  SELECT 9927807
  
  UNION
  
  SELECT 9927808
  
  UNION
  
  SELECT 9927809
  
  UNION
  
  SELECT 9927810
  
  UNION
  
  SELECT 9927811

  -- UNION
  -- SELECT 9927812
  --   UNION
  -- SELECT 9927813
  DECLARE @top INT = (
      SELECT count(1)
      FROM @MaterialId
      )

  --Primero borro antes de hacer cagadas
  DELETE oj.[dbo].[Expediente_Nomina_H]
  FROM pi.li.RequerimientoInformacionAsociada r
  INNER JOIN [material].[Material] m ON r.CausaId = m.OJ_ExpedienteOJId
  INNER JOIN @MaterialId m1 ON m1.MaterialId = m.MaterialId
  INNER JOIN oj.[dbo].[Expediente_Nomina_H] h ON h.IdExpediente = r.CausaId

  --Agregamos esto para mitigar el escenario donde, entre aplicaciones de este script, ocurran descargas de material por parte de algun usuario.
  DELETE material.DescargaMaterial
  FROM material.DescargaMaterial dm
  INNER JOIN material.MaterialPublicacion mp ON dm.MaterialPublicacionId = mp.MaterialPublicacionId
  INNER JOIN @MaterialId m ON mp.MaterialId = m.MaterialId

  DELETE material.MaterialPublicacion
  FROM material.MaterialPublicacion mp
  INNER JOIN @MaterialId m ON mp.MaterialId = m.MaterialId

  DELETE material.[Material]
  FROM material.Material mp
  INNER JOIN @MaterialId m ON mp.MaterialId = m.MaterialId

  SET IDENTITY_INSERT [material].[Material] ON

  DELETE [material].[MaterialPublicacion]
  WHERE MaterialId IN (
      SELECT MaterialId
      FROM @MaterialId
      )

  DELETE [material].[Material]
  WHERE MaterialId IN (
      SELECT MaterialId
      FROM @MaterialId
      );

  WITH FilasAleatoriasA
  AS (
    -- Paso 1: Obtener 5 filas al azar de la TablaA y asignarles un n�mero de fila
    SELECT *,
      ROW_NUMBER() OVER (
        ORDER BY (
            SELECT NULL
            )
        ) AS FilaNum
    FROM (
      SELECT TOP (@top) RequerimientoInformacionAsociadaEstadoId,
        max(CausaId) CausaId
      FROM li.RequerimientoInformacionAsociada
      GROUP BY RequerimientoInformacionAsociadaEstadoId
      ) AS SubA
    ),
  FilasAleatoriasB
  AS (
    -- Paso 2: Obtener 5 filas al azar de la TablaB y asignarles un n�mero de fila
    SELECT *,
      ROW_NUMBER() OVER (
        ORDER BY (
            SELECT NULL
            )
        ) AS FilaNum
    FROM (
      SELECT TOP (@top) *
      FROM @MaterialId
      ORDER BY MaterialId
      ) AS SubB
    )
  INSERT [material].[Material] (
    [MaterialId],
    [OJ_CdId],
    [OJ_CdTipoGrabacion],
    [OJ_ExpedienteOJId],
    [OJ_FechaMaterial]
    )
  -- Paso 3: Unir los dos conjuntos por el n�mero de fila para crear combinaciones �nicas
  SELECT
    --top 0
    B.MaterialId,
    B.MaterialId CdId,
    2 TipoMaterialId,
    A.CausaId,
    getdate()
  FROM FilasAleatoriasA AS A
  JOIN FilasAleatoriasB AS B ON A.FilaNum = B.FilaNum;

  IF @@ROWCOUNT <= 0
  BEGIN
      ;

    THROW 50000,
      'Error insertando registros en la tabla [material].[Material] para la funcionalidad InfoAsociadaDiDi',
      1;
  END

  SET IDENTITY_INSERT [material].[Material] OFF

  INSERT [material].[MaterialPublicacion] (
    [MaterialId],
    [MaterialPublicacionEstadoId],
    [FechaUltimaActualizacion],
    [FechaPublicacion],
    [FechaDesPublicacion],
    [FechaAltaSistema],
    [ExpedienteContrasenaId],
    [FechaParticionado],
    [HashPublicacion],
    [MaterialFechaGeneracion]
    )
  SELECT
    --TOP 0
    m.MaterialId,
    8,
    getdate(),
    getdate(),
    NULL,
    getdate(),
    6970,
    getdate(),
    --Agrego hash de publicación pulenta
    CONVERT(VARCHAR(128), HASHBYTES('SHA2_512', LTRIM(m.MaterialId)), 2),
    getdate() + 0.003
  FROM @MaterialId m

  IF @@ROWCOUNT <= 0
  BEGIN
      ;

    THROW 50000,
      'Error insertando registros en la tabla [material].[MaterialPublicacion] para la funcionalidad InfoAsociadaDiDi',
      1;
  END

  --GO
  INSERT INTO oj.[dbo].[Expediente_Nomina_H] (
    [IdExpediente],
    [IdOrganismoDepUsuario],
    [IdOrganismoDepExpediente],
    [IdUsuario],
    [Version],
    [FechaDesde],
    [FechaHasta],
    [FechaModif],
    [UsuarioModif],
    MaterialTipoId
    )
  SELECT r.CausaId,
    1378,
    1378,
    7330,
    1,
    getdate(),
    NULL,
    getdate(),
    1,
    2
  FROM pi.li.RequerimientoInformacionAsociada r
  INNER JOIN [material].[Material] m ON r.CausaId = m.OJ_ExpedienteOJId
  INNER JOIN @MaterialId m1 ON m1.MaterialId = m.MaterialId

  IF @@ROWCOUNT <= 0
  BEGIN
      ;

    THROW 50000,
      'Error insertando registros en la tabla [material].[Expediente_Nomina_H] para la funcionalidad InfoAsociadaDiDi',
      1;
  END
END
GO


