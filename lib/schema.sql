DROP TABLE IF EXISTS `logs`;
CREATE TABLE `logs` (
  `test_id` int(11) NOT NULL,
  `type` varchar(50) NOT NULL,
  `log` blob NOT NULL,
  `size` bigint(20) unsigned NOT NULL,
  `storage` varchar(200) NOT NULL DEFAULT '',
  `stack_trace` tinyint(1) NOT NULL DEFAULT '0',
  `patterns` varchar(200) NOT NULL DEFAULT '',
  PRIMARY KEY (`test_id`,`type`),
  CONSTRAINT `logs_ibfk_1` FOREIGN KEY (`test_id`) REFERENCES `tests` (`test_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `runs`;
CREATE TABLE `runs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `branch` varchar(100) NOT NULL,
  `sha` char(40) NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `title` varchar(150) CHARACTER SET utf8mb4 NOT NULL,
  `requester` varchar(50) NOT NULL,
  `is_nightly` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `nightly` (`is_nightly`,`timestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `builds`;
CREATE TABLE `builds` (
  `build_id` int(11) NOT NULL AUTO_INCREMENT,
  `run_id` int(11) NOT NULL,
  `status` enum('PENDING','BUILDING','BUILD DONE','BUILD FAILED','SKIPPED') NOT NULL,
  `started` timestamp NULL DEFAULT NULL,
  `finished` timestamp NULL DEFAULT NULL,
  `stderr` blob,
  `stdout` blob,
  `features` varchar(250) NOT NULL DEFAULT '',
  `is_release` tinyint(1) NOT NULL DEFAULT '0',
  `priority` tinyint(4) NOT NULL DEFAULT '0',
  `master_ip` int(10) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`build_id`),
  KEY `builds_ibfk_1` (`run_id`),
  KEY `builds_status` (`status`),
  KEY `builds_ip` (`master_ip`),
  CONSTRAINT `builds_ibfk_1` FOREIGN KEY (`run_id`) REFERENCES `runs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `tests`;
CREATE TABLE `tests` (
  `test_id` int(11) NOT NULL AUTO_INCREMENT,
  `run_id` int(11) NOT NULL,
  `build_id` int(11) DEFAULT NULL,
  `status` enum('FAILED','BUILD FAILED','CHECKOUT FAILED','SCP FAILED','TIMEOUT','PASSED','IGNORED','CANCELED','SKIPPED','RUNNING','PENDING') NOT NULL DEFAULT 'PENDING',
  `name` varchar(200) NOT NULL,
  `started` timestamp NULL DEFAULT NULL,
  `finished` timestamp NULL DEFAULT NULL,
  `select_after` int(11) NOT NULL DEFAULT '0',
  `priority` tinyint(4) NOT NULL,
  `is_release` tinyint(1) NOT NULL,
  `remote` tinyint(1) NOT NULL,
  `worker_ip` int(10) unsigned NOT NULL DEFAULT '0',
  `category` enum('pytest','mocknet','expensive') NOT NULL,
  PRIMARY KEY (`test_id`),
  KEY `run_id` (`run_id`),
  KEY `name` (`name`),
  KEY `tests_pick` (`status`,`select_after`,`build_id`,`category`),
  KEY `build_status` (`build_id`,`status`),
  CONSTRAINT `tests_ibfk_1` FOREIGN KEY (`run_id`) REFERENCES `runs` (`id`) ON DELETE CASCADE,
  CONSTRAINT `tests_ibfk_2` FOREIGN KEY (`build_id`) REFERENCES `builds` (`build_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `code` varchar(50) NOT NULL,
  `name` varchar(50) NOT NULL,
  PRIMARY KEY (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
