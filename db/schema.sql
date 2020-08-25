DROP TABLE IF EXISTS `logs`;
CREATE TABLE `logs` (
  `test_id` int(11) DEFAULT NULL,
  `type` varchar(50) DEFAULT NULL,
  `log` blob,
  `full_size` varchar(50) DEFAULT NULL,
  `storage` varchar(200) DEFAULT NULL,
  `stack_trace` tinyint(1) DEFAULT '0',
  KEY `test_id` (`test_id`),
  KEY `test_id_2` (`test_id`,`type`),
  KEY `test_id_3` (`test_id`,`type`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `runs`;
CREATE TABLE `runs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `branch` varchar(50) DEFAULT NULL,
  `sha` varchar(50) DEFAULT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `user` varchar(50) DEFAULT NULL,
  `title` varchar(200) DEFAULT NULL,
  `type` varchar(50) DEFAULT NULL,
  `requester` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=63 DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `tests`;
CREATE TABLE `tests` (
  `test_id` int(11) NOT NULL AUTO_INCREMENT,
  `run_id` int(11) DEFAULT NULL,
  `status` varchar(50) DEFAULT NULL,
  `name` varchar(200) DEFAULT NULL,
  `started` timestamp NULL DEFAULT NULL,
  `finished` timestamp NULL DEFAULT NULL,
  `hostname` varchar(50) DEFAULT NULL,
  `test_started` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`test_id`),
  KEY `run_id` (`run_id`),
  KEY `name` (`name`),
  KEY `run_id_2` (`run_id`),
  CONSTRAINT `tests_ibfk_1` FOREIGN KEY (`run_id`) REFERENCES `runs` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=7476 DEFAULT CHARSET=latin1;

